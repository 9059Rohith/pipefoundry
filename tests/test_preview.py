"""Deployment review must never become a second mutation path."""

import json
import subprocess
import sys
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline


def config(**changes):
    return Pipeline.model_validate({"name": "preview-orders", "schedule": "0 * * * *", **changes})


def snapshot(platform):
    with platform.connect() as db:
        tables = {
            table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]
            for table in ("revisions", "audit", "operations", "cluster_targets", "artifacts")
        }
    files = {
        str(path.relative_to(platform.root)): path.read_bytes()
        for path in platform.root.rglob("*")
        if path.is_file() and not path.name.startswith("metadata.db")
    }
    return tables, files


def test_preview_create_and_changes_are_bounded_and_do_not_echo_config(tmp_path):
    platform = Platform(tmp_path)
    before = snapshot(platform)
    result = platform.preview(config())
    assert result["action"] == "create"
    assert result["current"] is None
    assert result["changes"] == [
        {"path": "config", "kind": "added"},
        {"path": "executor", "kind": "added"},
    ]
    assert len(result["desired_fingerprint"]) == 64
    assert "orders.db" not in json.dumps(result)
    assert snapshot(platform) == before


def test_preview_empty_revision_and_operation_are_read_in_one_statement(tmp_path, monkeypatch):
    platform = Platform(tmp_path)
    original = platform.connect
    statements = []

    @contextmanager
    def traced():
        with original() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(platform, "connect", traced)
    with platform.operation(config().name):
        statements.clear()
        result = platform.preview(config())
        assert result["current"] is None
        assert result["operation_in_progress"] is True
        assert len([sql for sql in statements if sql.startswith("SELECT")]) == 1


def test_preview_canonical_noop_update_and_executor_change_without_effects(tmp_path, monkeypatch):
    platform = Platform(tmp_path)
    platform.deploy(config())
    before = snapshot(platform)

    def forbidden(*args, **kwargs):
        pytest.fail("preview attempted an external effect or artifact restoration")

    for method in ("_run", "_execute", "_restore_revision", "_new_revision", "operation"):
        monkeypatch.setattr(platform, method, forbidden)
    desired = Pipeline.model_validate({"name": "preview-orders", "schedule": "0  * * * *"})
    noop = platform.preview(desired)
    assert noop["action"] == "no-op"
    assert noop["changes"] == []
    assert noop["current"]["fingerprint"] == noop["desired_fingerprint"]
    changed = platform.preview(
        config(schedule="30 2 * * *", resources={"cpu_millis": 500}), "kubernetes"
    )
    assert changed["action"] == "update"
    assert changed["changes"] == [
        {"path": "config.resources.cpu_millis", "kind": "changed"},
        {"path": "config.schedule", "kind": "changed"},
        {"path": "executor", "kind": "changed"},
    ]
    assert changed["current"]["revision"] == 1
    assert len(changed["changes"]) <= 12
    assert snapshot(platform) == before


@pytest.mark.parametrize("status", ["rendered", "failed", "torn_down", "running", "deploying"])
def test_preview_equal_inactive_or_unfinished_revision_requires_update(tmp_path, status):
    platform = Platform(tmp_path)
    platform.render(config())
    with platform.connect() as db:
        db.execute("UPDATE revisions SET status=?,executor='local'", (status,))
    assert platform.preview(config())["action"] == "update"


def test_preview_reports_active_operation_without_acquiring_or_releasing_it(tmp_path):
    platform = Platform(tmp_path)
    platform.deploy(config())
    with platform.operation(config().name):
        before = snapshot(platform)
        result = platform.preview(config())
        assert result["operation_in_progress"] is True
        assert result["action"] == "update"
        assert snapshot(platform) == before


def test_preview_first_deploy_lease_and_all_allowed_changes_are_visible(tmp_path):
    platform = Platform(tmp_path)
    with platform.operation(config().name):
        result = platform.preview(config())
        assert result["action"] == "create"
        assert result["operation_in_progress"] is True
    platform.deploy(config())
    desired = config(
        schedule="30 2 * * *",
        input={"connector": "spark_json", "path": "private-sentinel.json"},
        output={"connector": "parquet", "path": "private-sentinel-parquet"},
        resources={"cpu_millis": 500, "memory_mib": 1024},
    )
    result = platform.preview(desired, "kubernetes")
    assert len(result["changes"]) == 8
    assert result["changes_truncated"] is False
    assert "private-sentinel" not in json.dumps(result)


def test_preview_rejects_corrupt_record_without_echoing_stored_payload(tmp_path):
    platform = Platform(tmp_path)
    platform.render(config())
    with platform.connect() as db:
        db.execute("UPDATE revisions SET config=?", ('{"token":"private-sentinel"}',))
    with pytest.raises(ValueError, match="^stored revision config is invalid$"):
        platform.preview(config())


def test_preview_api_auth_validation_and_payload_secrets_are_safe(tmp_path, monkeypatch):
    from pipefoundry.api import create_app

    secret = "private-sentinel-never-echo"
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "p" * 32)
    monkeypatch.setenv("PIPEFOUNDRY_ORDERS_URL", "https://example.com/" + secret)
    client = TestClient(create_app(tmp_path))
    headers = {"Authorization": "Bearer " + "p" * 32}
    body = {"config": config().model_dump(), "executor": "local"}
    assert client.post("/deployments/preview", json=body).status_code == 401
    response = client.post("/deployments/preview", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["action"] == "create"
    schema = client.get("/openapi.json", headers=headers).json()
    response_schema = schema["paths"]["/deployments/preview"]["post"]["responses"]["200"]
    assert response_schema["content"]["application/json"]["schema"]["$ref"].endswith(
        "/DeploymentPreview"
    )
    preview_schema = schema["components"]["schemas"]["DeploymentPreview"]
    assert preview_schema["properties"]["action"]["enum"] == ["create", "update", "no-op"]
    assert preview_schema["properties"]["changes"]["maxItems"] == 12
    for invalid in (
        {"token": secret},
        {"schedule": secret},
        {"name": secret + "!"},
        {"output": {"path": "../" + secret}},
    ):
        body["config"] = {**config().model_dump(), **invalid}
        response = client.post("/deployments/preview", json=body, headers=headers)
        assert response.status_code == 422
        assert secret not in response.text
    assert client.get("/pipelines", headers=headers).json() == []


def test_preview_rejects_unknown_executor_and_hosted_ephemeral_output(tmp_path):
    platform = Platform(tmp_path)
    with pytest.raises(ValueError, match="executor"):
        platform.preview(config(), "shell")
    platform.durable = True  # Output compatibility must fail before any DB access.
    with pytest.raises(ValueError, match="PostgreSQL output"):
        platform.preview(config())


def test_cli_preview_outputs_json_without_creating_revisions_and_sanitizes_errors(tmp_path):
    source = tmp_path / "pipeline.json"
    source.write_text(config().model_dump_json())
    command = [
        sys.executable,
        "-m",
        "pipefoundry",
        "--state-dir",
        str(tmp_path / "state"),
        "preview",
        str(source),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["action"] == "create"
    assert not (tmp_path / "state/revisions").exists()
    source.write_text(json.dumps({"name": "secret-sentinel!", "schedule": "bad"}))
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    assert "secret-sentinel" not in result.stderr
