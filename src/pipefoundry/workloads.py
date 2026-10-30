"""Real bounded ingestion workloads, shared by local and Kubernetes executors."""

import ipaddress
import json
import os
import re
import sqlite3
import ssl
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg
from pydantic import Field, TypeAdapter

from pipefoundry.models import StrictModel

MAX_RESPONSE_BYTES = 1_048_576
MAX_ROWS = 10_000
FIXTURE = [
    {"id": "order-001", "amount_cents": 1250, "currency": "usd"},
    {"id": "order-002", "amount_cents": 2000, "currency": "eur"},
    {"id": "order-003", "amount_cents": 1000, "currency": "usd"},
]


class Order(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    amount_cents: int = Field(ge=0, le=1_000_000_000, strict=True)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")


def normalize_orders(rows: list[dict]) -> list[dict]:
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("input must contain 1 to 10000 records")
    checked = TypeAdapter(list[Order]).validate_python(rows)
    # Last observation wins for duplicate IDs within a partition.
    return list(
        {row.id: {**row.model_dump(), "currency": row.currency.upper()} for row in checked}.values()
    )


def _connector_url() -> str:
    url = os.environ.get("PIPEFOUNDRY_ORDERS_URL", "")
    allowed = {
        host.strip().lower()
        for host in os.environ.get("PIPEFOUNDRY_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    parsed = urlsplit(url)
    authority = parsed.netloc.lower()
    default_authority = parsed.hostname if parsed.port in {None, 443} else authority
    if (
        parsed.scheme != "https"
        or (authority not in allowed and default_authority not in allowed)
        or parsed.username
        or parsed.password
        or parsed.fragment
        or not allowed
    ):
        raise ValueError("orders URL must use HTTPS and an administrator host allowlist")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("orders URL IP must be public and allowlisted")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname):
        raise ValueError("invalid allowlisted hostname")
    return url


def fetch_orders(client: httpx.Client | None = None, retry_delay: float = 0.1) -> list[dict]:
    url = _connector_url()
    owned = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(10, connect=3),
        follow_redirects=False,
        trust_env=False,
        verify=ssl.create_default_context(cafile=os.environ.get("PIPEFOUNDRY_CA_BUNDLE")),
    )
    try:
        for attempt in range(3):
            try:
                with client.stream("GET", url, timeout=10, follow_redirects=False) as response:
                    if response.is_redirect:
                        raise ValueError("connector redirects are forbidden")
                    response.raise_for_status()
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        payload.extend(chunk)
                        if len(payload) > MAX_RESPONSE_BYTES:
                            raise ValueError("connector response too large")
                    return normalize_orders(json.loads(payload))
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                    exc.response.status_code >= 500 or exc.response.status_code == 429
                )
                if not retryable or attempt == 2:
                    raise RuntimeError("orders connector failed after bounded retries") from None
                time.sleep(retry_delay * 2**attempt)
        raise RuntimeError("orders connector failed")  # pragma: no cover
    finally:
        if owned:
            client.close()


SQLITE_DDL = """CREATE TABLE IF NOT EXISTS orders (
    partition_date TEXT NOT NULL, id TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
    currency TEXT NOT NULL CHECK(length(currency) = 3),
    PRIMARY KEY(partition_date, id))"""
QUALITY_SQL = """SELECT COUNT(*) FROM orders WHERE amount_cents < 0
    OR length(currency) <> 3 OR currency <> upper(currency) OR id = ''"""


def ingest(rows: list[dict], path: Path, partition: str) -> dict:
    date.fromisoformat(partition)
    rows = normalize_orders(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute(SQLITE_DDL)
        conn.executemany(
            """INSERT INTO orders VALUES (?, ?, ?, ?) ON CONFLICT(partition_date, id)
            DO UPDATE SET amount_cents=excluded.amount_cents, currency=excluded.currency""",
            [(partition, row["id"], row["amount_cents"], row["currency"]) for row in rows],
        )
        invalid = conn.execute(QUALITY_SQL).fetchone()[0]
        if invalid:
            raise ValueError("SQL data quality check failed")
        total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    return {"rows": len(rows), "total_rows": total, "quality": {"invalid_rows": invalid}}


def ingest_postgres(rows: list[dict], partition: str) -> dict:
    date.fromisoformat(partition)
    rows = normalize_orders(rows)
    dsn = os.environ.get("PIPEFOUNDRY_POSTGRES_DSN")
    if not dsn:
        raise ValueError("PIPEFOUNDRY_POSTGRES_DSN is required")
    with psycopg.connect(dsn, connect_timeout=5, options="-c statement_timeout=10000") as conn:
        with conn.cursor() as cur:
            cur.execute(SQLITE_DDL.replace("partition_date TEXT", "partition_date DATE"))
            cur.executemany(
                """INSERT INTO orders VALUES (%s, %s, %s, %s)
                ON CONFLICT(partition_date, id) DO UPDATE
                SET amount_cents=excluded.amount_cents, currency=excluded.currency""",
                [(partition, row["id"], row["amount_cents"], row["currency"]) for row in rows],
            )
            cur.execute(QUALITY_SQL)
            invalid = cur.fetchone()[0]
            if invalid:
                raise ValueError("SQL data quality check failed")
            cur.execute("SELECT COUNT(*) FROM orders")
            total = cur.fetchone()[0]
    return {"rows": len(rows), "total_rows": total, "quality": {"invalid_rows": invalid}}
