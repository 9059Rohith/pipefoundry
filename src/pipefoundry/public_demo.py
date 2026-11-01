"""Persistent, fail-closed public AI allowance. No execution permissions are granted."""

import hashlib
import hmac
import ipaddress
import os
import sqlite3
import time
from contextlib import contextmanager

import psycopg
from fastapi import HTTPException, Request

PUBLIC_REPOSITORY = "9059Rohith/pipefoundry"
PUBLIC_MODEL = "gemini-3.5-flash-lite"
CANONICAL_ORIGIN = "https://rohith-pipefoundry.vercel.app"
DDL = """CREATE TABLE IF NOT EXISTS pf_public_ai_limits (
    bucket_key TEXT NOT NULL, window_start BIGINT NOT NULL, used INTEGER NOT NULL,
    PRIMARY KEY (bucket_key, window_start)
)"""


def unavailable():
    return HTTPException(503, "Public AI demo is temporarily unavailable. No AI request was made.")


def enforce_origin(request: Request):
    origin = request.headers.get("origin")
    scheme = "https" if os.getenv("VERCEL") == "1" else request.url.scheme
    request_origin = f"{scheme}://{request.url.netloc}"
    if origin is not None and origin not in {CANONICAL_ORIGIN, request_origin}:
        raise HTTPException(403, "Cross-origin public AI requests are not allowed")


def client_identity(request: Request):
    secret = os.getenv("PIPEFOUNDRY_API_TOKEN", "")
    if len(secret) < 32:
        raise unavailable()
    peer = request.client.host if request.client else "unknown"
    candidate = request.headers.get("x-forwarded-for", "") if os.getenv("VERCEL") == "1" else ""
    try:
        address = str(ipaddress.ip_address(candidate.strip()))
    except ValueError:
        try:
            address = str(ipaddress.ip_address(peer))
        except ValueError:
            address = "unknown-peer"
    return hmac.new(secret.encode(), address.encode(), hashlib.sha256).hexdigest()


class DemoLimiter:
    def __init__(self, *, dsn=None, sqlite_path=None):
        self.dsn = dsn
        self.sqlite_path = sqlite_path

    @classmethod
    def configured(cls):
        dsn = os.getenv("PIPEFOUNDRY_METADATA_DSN")
        local = os.getenv("PIPEFOUNDRY_DEMO_LIMIT_DB") if os.getenv("VERCEL") != "1" else None
        if not dsn and not local:
            raise unavailable()
        return cls(dsn=dsn, sqlite_path=local)

    @contextmanager
    def connection(self):
        if self.dsn:
            with psycopg.connect(self.dsn, connect_timeout=5) as connection:
                connection.execute("SET LOCAL statement_timeout = '5s'")
                connection.execute("SET LOCAL lock_timeout = '3s'")
                connection.execute("SELECT pg_advisory_xact_lock(1346785351,8)")
                yield connection
        elif self.sqlite_path:
            connection = sqlite3.connect(self.sqlite_path, timeout=5, isolation_level=None)
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
        else:
            raise unavailable()

    def consume(self, identity, *, now=None):
        instant = int(time.time() if now is None else now)
        buckets = [
            ("client:" + identity, 600, 3),
            ("global:minute", 60, 2),
            ("global:day", 86400, 30),
        ]

        def statement(value):
            return value.replace("?", "%s") if self.dsn else value

        try:
            with self.connection() as connection:
                connection.execute(DDL)
                windows = [
                    (key, instant // seconds * seconds, seconds, cap)
                    for key, seconds, cap in buckets
                ]
                retry = 0
                for key, start, seconds, cap in windows:
                    row = connection.execute(
                        statement(
                            "SELECT used FROM pf_public_ai_limits "
                            "WHERE bucket_key=? AND window_start=?"
                        ),
                        (key, start),
                    ).fetchone()
                    if row and row[0] >= cap:
                        retry = max(retry, start + seconds - instant)
                if retry:
                    raise HTTPException(
                        429,
                        "Public demo allowance reached. Please try again later.",
                        headers={"Retry-After": str(max(1, retry))},
                    )
                for key, start, _, _ in windows:
                    connection.execute(
                        statement(
                            "INSERT INTO pf_public_ai_limits VALUES(?,?,1) "
                            "ON CONFLICT(bucket_key,window_start) DO UPDATE "
                            "SET used=pf_public_ai_limits.used+1"
                        ),
                        (key, start),
                    )
                connection.execute(
                    statement("DELETE FROM pf_public_ai_limits WHERE window_start<?"),
                    (instant - 86400,),
                )
        except (psycopg.Error, sqlite3.Error, OSError) as exc:
            raise unavailable() from exc
