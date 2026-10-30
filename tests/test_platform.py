import json
import sqlite3
import subprocess
import sys

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError


def config(**changes):
    result = {
        "name": "orders-demo",
        "schedule": "0 * * * *",
        "input": {"connector": "fixture"},
        "transform": "normalize_orders",
        "output": {"connector": "sqlite", "path": "orders.db"},
        "resources": {"cpu_millis": 100, "memory_mib": 128},
    }
    result.update(changes)
    return result


def test_config_rejects_url_injection_traversal_and_resource_exhaustion():
    from pipefoundry.models import Pipeline

    assert Pipeline.model_validate(config()).name == "orders-demo"
    attacks = [
        {"name": "../../escape"},
        {"name": "orders; touch pwned"},
        {"schedule": "not cron"},
        {"schedule": "* * * * * *"},
        {"input": {"connector": "http", "url": "http://169.254.169.254"}},
        {"output": {"connector": "sqlite", "path": "../escape.db"}},
        {"output": {"connector": "sqlite", "path": "C:\\secrets.db"}},
        {"resources": {"cpu_millis": 100000, "memory_mib": 100000}},
        {"transform": "exec('bad')"},
    ]
    for attack in attacks:
        with pytest.raises(ValidationError):
            Pipeline.model_validate(config(**attack))


def test_revision_render_local_run_backfill_rollback_and_audit(tmp_path):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    platform = Platform(tmp_path)
    first = platform.deploy(Pipeline.model_validate(config()), executor="local")
    assert first["revision"] == 1
    assert first["status"] == "succeeded"
    with sqlite3.connect(tmp_path / "data" / "orders.db") as connection:
        assert connection.execute("select count(*), sum(amount_cents) from orders").fetchone() == (
            3,
            4250,
        )
    revision = tmp_path / "revisions" / "orders-demo" / "1"
    manifest = yaml.safe_load((revision / "cronjob.yaml").read_text())
    assert manifest["spec"]["schedule"] == "0 * * * *"
    assert (
        manifest["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["resources"][
            "limits"
        ]["memory"]
        == "128Mi"
    )
    assert (revision / "airflow_dag.py").is_file()
    second = platform.deploy(Pipeline.model_validate(config(schedule="0 2 * * *")), "local")
    assert second["revision"] == 2
    backfill = platform.backfill("orders-demo", "2026-01-01", "2026-01-03")
    assert backfill["partitions"] == 3
    with sqlite3.connect(tmp_path / "data" / "orders.db") as connection:
        assert connection.execute("select count(*) from orders").fetchone()[0] == 12
    rollback = platform.rollback("orders-demo", 1)
    assert rollback["revision"] == 3
    assert platform.config("orders-demo").schedule == "0 * * * *"
    assert len(platform.logs("orders-demo")) > 0
    assert [event["action"] for event in platform.audit("orders-demo")] == [
        "deploy",
        "deploy",
        "backfill",
        "rollback",
    ]
    platform.teardown("orders-demo")
    assert platform.status("orders-demo")["status"] == "torn_down"
    assert (revision / "pipeline.json").exists()


def test_render_is_deterministic_and_does_not_claim_deployment(tmp_path):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    platform = Platform(tmp_path)
    rendered = platform.render(Pipeline.model_validate(config()))
    assert rendered["status"] == "rendered"
    assert platform.status("orders-demo")["status"] == "rendered"
    with pytest.raises(ValueError, match="not deployed"):
        platform.backfill("orders-demo", "2026-01-01", "2026-01-02")
    with pytest.raises(ValueError):
        platform.rollback("orders-demo", 999)


def test_api_fails_closed_and_lifecycle(tmp_path, monkeypatch):
    from pipefoundry.api import create_app

    monkeypatch.delenv("PIPEFOUNDRY_API_TOKEN", raising=False)
    client = TestClient(create_app(tmp_path))
    assert client.get("/health/live").status_code == 200
    assert client.get("/pipelines").status_code == 503
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "t" * 32)
    assert client.get("/pipelines").status_code == 401
    headers = {"Authorization": "Bearer " + "t" * 32}
    assert client.post("/pipelines", json={"config": config()}, headers=headers).status_code == 201
    assert client.get("/pipelines/orders-demo", headers=headers).json()["status"] == "succeeded"
    assert client.get("/pipelines/orders-demo/logs", headers=headers).json()["logs"]
    assert (
        client.post(
            "/pipelines/orders-demo/backfill",
            json={"start": "2026-01-01", "end": "2026-01-02"},
            headers=headers,
        ).json()["partitions"]
        == 2
    )
    assert (
        client.post(
            "/pipelines", json={"config": config(name="../../bad")}, headers=headers
        ).status_code
        == 422
    )
    assert client.delete("/pipelines/orders-demo", headers=headers).status_code == 200


def test_cli_real_deploy_and_invalid_config(tmp_path):
    source = tmp_path / "pipeline.json"
    source.write_text(json.dumps(config()))
    command = [sys.executable, "-m", "pipefoundry", "--state-dir", str(tmp_path / "state")]
    result = subprocess.run(command + ["deploy", str(source)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "succeeded"
    result = subprocess.run(command + ["status", "orders-demo"], capture_output=True, text=True)
    assert json.loads(result.stdout)["revision"] == 1
    source.write_text(json.dumps(config(name="../escape")))
    result = subprocess.run(command + ["validate", str(source)], capture_output=True, text=True)
    assert result.returncode != 0


def test_missing_cluster_tools_persists_failure(tmp_path, monkeypatch):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    monkeypatch.setenv("PATH", "")
    platform = Platform(tmp_path)
    with pytest.raises(RuntimeError, match="kubectl"):
        platform.deploy(Pipeline.model_validate(config()), "kubernetes")
    assert platform.status("orders-demo")["status"] == "failed"


def test_backfill_bound_and_safe_paths(tmp_path):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    platform = Platform(tmp_path)
    platform.deploy(Pipeline.model_validate(config()), "local")
    for name in ["../escape", "/tmp/x", "orders;ls"]:
        with pytest.raises(ValueError):
            platform.status(name)
    with pytest.raises(ValueError):
        platform.backfill("orders-demo", "2020-01-01", "2026-01-01")
    with pytest.raises(ValueError):
        platform.backfill("orders-demo", "2026-01-02", "2026-01-01")
