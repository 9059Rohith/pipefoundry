"""Protected public contracts, including real CLI workers and review-file tampering."""

import json
import subprocess
import sys

from fastapi.testclient import TestClient

from pipefoundry.models import Pipeline


def test_release_api_requires_auth_and_rejects_payload_overrides(tmp_path, monkeypatch):
    from pipefoundry.api import create_app

    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "r" * 32)
    client = TestClient(create_app(tmp_path))
    headers = {"Authorization": "Bearer " + "r" * 32}
    config = {"name": "api-release", "schedule": "0 * * * *"}
    assert client.post("/releases/plan", json={"config": config}).status_code == 401
    response = client.post("/releases/plan", headers=headers, json={"config": config})
    assert response.status_code == 200
    plan = response.json()
    apply = {
        "plan_id": plan["plan_id"],
        "digest": plan["digest"],
        "idempotency_key": "api-release-001",
    }
    poisoned = {**apply, "config": {"token": "secret-never-echo"}}
    response = client.post("/releases/apply", headers=headers, json=poisoned)
    assert response.status_code == 422
    assert "secret-never-echo" not in response.text
    result = client.post("/releases/apply", headers=headers, json=apply)
    assert result.status_code == 200
    assert result.json()["state"] == "succeeded"
    assert client.post("/releases/apply", headers=headers, json=apply).json() == result.json()
    assert client.get("/releases/receipts/api-release-001", headers=headers).json() == result.json()


def test_cli_review_file_is_not_an_executable_plan(tmp_path):
    config = tmp_path / "pipeline.json"
    config.write_text(Pipeline(name="cli-release", schedule="0 * * * *").model_dump_json())
    command = [sys.executable, "-m", "pipefoundry", "--state-dir", str(tmp_path / "state")]
    result = subprocess.run([*command, "plan", str(config)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    review = tmp_path / "review.json"
    review.write_text(json.dumps(plan))
    apply = [*command, "apply", str(review), "--idempotency-key", "cli-release-001"]
    result = subprocess.run(apply, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["state"] == "succeeded"
    plan["config"]["schedule"] = "30 * * * *"
    review.write_text(json.dumps(plan))
    result = subprocess.run(apply, capture_output=True, text=True)
    assert result.returncode == 1
    assert "integrity" in result.stderr
