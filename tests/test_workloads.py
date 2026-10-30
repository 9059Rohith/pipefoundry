import json
import os
import sqlite3

import httpx
import pytest


def test_ingestion_is_idempotent_and_quality_failure_rolls_back(tmp_path):
    from pipefoundry.workloads import ingest, normalize_orders

    path = tmp_path / "orders.db"
    rows = [{"id": "a", "amount_cents": 100, "currency": "usd"}]
    assert ingest(rows, path, "2026-01-01")["total_rows"] == 1
    assert ingest(rows, path, "2026-01-01")["total_rows"] == 1
    with pytest.raises(ValueError):
        normalize_orders([{"id": "b", "amount_cents": -10, "currency": "usd"}])
    with sqlite3.connect(path) as conn:
        assert conn.execute("select currency from orders").fetchone()[0] == "USD"


def test_http_connector_rejects_ssrf_redirect_and_retries(monkeypatch):
    from pipefoundry.workloads import fetch_orders

    monkeypatch.setenv("PIPEFOUNDRY_ORDERS_URL", "http://169.254.169.254/latest/meta-data")
    monkeypatch.setenv("PIPEFOUNDRY_ALLOWED_HOSTS", "api.example.com")
    with pytest.raises(ValueError, match="allowlist"):
        fetch_orders()
    monkeypatch.setenv("PIPEFOUNDRY_ORDERS_URL", "https://api.example.com/orders")
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        if count < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=[{"id": "a", "amount_cents": 25, "currency": "USD"}])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert fetch_orders(client=client, retry_delay=0)[0]["id"] == "a"
    assert count == 3
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"Location": "http://169.254.169.254"})
        )
    ) as client:
        with pytest.raises(ValueError, match="redirect"):
            fetch_orders(client=client, retry_delay=0)


def test_http_response_and_record_bounds(monkeypatch):
    from pipefoundry.workloads import fetch_orders

    monkeypatch.setenv("PIPEFOUNDRY_ORDERS_URL", "https://api.example.com/orders")
    monkeypatch.setenv("PIPEFOUNDRY_ALLOWED_HOSTS", "api.example.com")
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 1_100_000))
    ) as client:
        with pytest.raises(ValueError, match="large"):
            fetch_orders(client=client, retry_delay=0)


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("PIPEFOUNDRY_POSTGRES_DSN"), reason="PostgreSQL DSN required"
)
def test_postgres_real_upsert_and_sql_quality():
    from pipefoundry.workloads import ingest_postgres

    rows = [{"id": "integration-a", "amount_cents": 25, "currency": "USD"}]
    one = ingest_postgres(rows, "2026-01-01")
    two = ingest_postgres(rows, "2026-01-01")
    assert two["total_rows"] == one["total_rows"]
    assert two["quality"]["invalid_rows"] == 0


@pytest.mark.spark
@pytest.mark.skipif(not os.environ.get("PIPEFOUNDRY_TEST_SPARK"), reason="Spark runtime opt in")
def test_spark_real_json_to_parquet(tmp_path):
    from pipefoundry.spark_job import transform

    source = tmp_path / "input.json"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"id": "a", "amount_cents": 100, "currency": "usd"},
                {"id": "b", "amount_cents": 200, "currency": "eur"},
            ]
        )
    )
    result = transform(source, tmp_path / "parquet")
    assert result["rows"] == 2
    assert list((tmp_path / "parquet").rglob("*.parquet"))


@pytest.mark.postgres
@pytest.mark.skipif(
    not os.environ.get("PIPEFOUNDRY_POSTGRES_DSN"), reason="PostgreSQL DSN required"
)
def test_real_https_api_to_postgres_through_worker(tmp_path, monkeypatch):
    import shutil
    import ssl
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import psycopg

    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    openssl = shutil.which("openssl")
    if not openssl:
        from pathlib import Path

        candidate = Path("C:/Program Files/Git/usr/bin/openssl.exe")
        openssl = str(candidate) if candidate.exists() else None
    if not openssl:
        pytest.skip("openssl required to generate ephemeral HTTPS test certificate")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
        ],
        check=True,
        capture_output=True,
    )
    attempts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            attempts.append(self.path)
            if len(attempts) == 1:
                self.send_response(503)
                self.end_headers()
                return
            body = json.dumps(
                [{"id": "https-integration", "amount_cents": 999, "currency": "usd"}]
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except OSError:
        pytest.skip("localhost HTTPS listener unavailable")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    authority = f"localhost:{server.server_port}"
    monkeypatch.setenv("PIPEFOUNDRY_ORDERS_URL", f"https://{authority}/orders")
    monkeypatch.setenv("PIPEFOUNDRY_ALLOWED_HOSTS", authority)
    monkeypatch.setenv("PIPEFOUNDRY_CA_BUNDLE", str(cert))
    try:
        platform = Platform(tmp_path / "state")
        config = Pipeline.model_validate(
            {
                "name": "https-postgres",
                "schedule": "0 * * * *",
                "input": {"connector": "orders_api"},
                "output": {"connector": "postgres"},
            }
        )
        assert platform.deploy(config)["status"] == "succeeded"
        assert platform.deploy(config)["status"] == "succeeded"
        assert len(attempts) == 3
        with psycopg.connect(os.environ["PIPEFOUNDRY_POSTGRES_DSN"]) as conn:
            result = conn.execute(
                "SELECT count(*), max(amount_cents), max(currency) FROM orders WHERE id=%s",
                ("https-integration",),
            ).fetchone()
        assert result == (1, 999, "USD")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
