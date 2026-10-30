import json
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_platform import config


def test_oversize_api_body_and_short_token_are_rejected(tmp_path, monkeypatch):
    from pipefoundry.api import create_app

    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "short")
    client = TestClient(create_app(tmp_path))
    assert client.get("/health/ready").status_code == 503
    assert client.get("/pipelines", headers={"Authorization": "Bearer short"}).status_code == 503
    assert client.post("/pipelines", content="x" * 33000).status_code == 413


def test_non_ascii_bearer_fails_auth_without_server_error(tmp_path, monkeypatch):
    from pipefoundry.api import create_app

    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "t" * 32)
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert (
        client.get("/pipelines", headers=[(b"authorization", b"Bearer \xff\xfe")]).status_code
        == 401
    )
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "")
    assert client.get("/pipelines").status_code == 503


def test_tampered_revision_cannot_be_rolled_back(tmp_path):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    platform = Platform(tmp_path)
    platform.deploy(Pipeline.model_validate(config()))
    revision = platform.revision_dir("orders-demo", 1)
    (revision / "pipeline.json").write_text(json.dumps(config(schedule="* * * * *")))
    with pytest.raises(ValueError, match="integrity"):
        platform.rollback("orders-demo", 1)


def test_sql_quality_check_failure_rolls_back_the_entire_batch(tmp_path):
    from pipefoundry.workloads import ingest

    path = tmp_path / "orders.db"
    ingest([{"id": "a", "amount_cents": 10, "currency": "USD"}], path, "2026-01-01")
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE orders SET currency='usd' WHERE id='a'")
    with pytest.raises(ValueError, match="quality"):
        ingest([{"id": "b", "amount_cents": 20, "currency": "USD"}], path, "2026-01-01")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT id FROM orders ORDER BY id").fetchall() == [("a",)]


def test_active_operation_rejects_another_process_instance(tmp_path):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    one, two = Platform(tmp_path), Platform(tmp_path)
    with one.operation("orders-demo"):
        with pytest.raises(ValueError, match="active operation"):
            two.deploy(Pipeline.model_validate(config()))
    assert two.deploy(Pipeline.model_validate(config()))["status"] == "succeeded"


def test_metadata_connections_close_after_transaction(tmp_path):
    from pipefoundry.engine import Platform

    platform = Platform(tmp_path)
    with platform.connect() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_data_root_symlink_cannot_escape_workspace(tmp_path):
    from pipefoundry.worker import data_path

    root, outside = tmp_path / "state", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "data").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this Windows account")
    with pytest.raises(ValueError, match="escapes"):
        data_path(root, "stolen.db")


def test_revision_root_symlink_cannot_escape_workspace(tmp_path):
    from pipefoundry.engine import Platform

    root, outside = tmp_path / "state", tmp_path / "outside"
    outside.mkdir()
    platform = Platform(root)
    try:
        (root / "revisions").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable on this Windows account")
    with pytest.raises(ValueError, match="escapes"):
        platform.revision_dir("orders-demo", 1)
