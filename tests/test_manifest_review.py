import copy
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from pipefoundry.models import Pipeline
from pipefoundry.render import objects


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "a" * 40)
    monkeypatch.setenv("PIPEFOUNDRY_SEED_DEMO", "false")
    monkeypatch.delenv("PIPEFOUNDRY_WORKER_IMAGE", raising=False)
    from pipefoundry.api import create_app

    with TestClient(create_app(tmp_path)) as client:
        yield client


def payload(**changes):
    return {"name": "orders-hourly", "schedule": "0 * * * *", **changes}


def test_public_review_audits_actual_renderer_and_export_digest(client, tmp_path):
    before = list(tmp_path.rglob("*"))
    response = client.post("/workbench/api/review", json={"config": payload()})
    assert response.status_code == 200
    result = response.json()
    evidence = result["evidence"]
    assert evidence["current"]["objects"] == objects(Pipeline.model_validate(payload()), 1)
    assert evidence["current"]["summary"] == {"pass": 10, "warn": 1, "fail": 0, "na": 1}
    checks = {check["id"]: check for check in evidence["current"]["checks"]}
    assert checks["image-digest"]["status"] == "warn"
    assert checks["deployment-progress"]["status"] == "na"
    assert evidence["cluster_validation"] == "not performed"
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert result["evidence_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert (
        response.json() == client.post("/workbench/api/review", json={"config": payload()}).json()
    )
    assert before == list(tmp_path.rglob("*"))
    assert client.post("/releases/apply", json={}).status_code == 401


def test_digest_pin_uses_actual_operator_image(client, monkeypatch):
    monkeypatch.setenv("PIPEFOUNDRY_WORKER_IMAGE", "example/worker@sha256:" + "a" * 64)
    current = client.post("/workbench/api/review", json={"config": payload()}).json()["evidence"][
        "current"
    ]
    assert current["summary"]["warn"] == 0
    assert current["summary"]["pass"] == 11


@pytest.mark.parametrize(
    "body",
    [
        {"config": {**payload(), "command": "SECRET-MARKER"}},
        {"config": payload(output={"path": "../../SECRET-MARKER"})},
        {"config": payload(resources={"cpu_millis": True})},
        {"config": payload(), "baseline": {**payload(), "image": "SECRET-MARKER"}},
        {"config": payload(), "kubectl": "SECRET-MARKER"},
        {"config": "SECRET-MARKER"},
    ],
)
def test_review_rejects_unsafe_and_unknown_config_without_reflection(client, body):
    result = client.post("/workbench/api/review", json=body)
    assert result.status_code == 422
    assert "SECRET-MARKER" not in result.text


def test_review_size_boundary_and_page(client):
    assert client.post("/workbench/api/review", content=b"x" * 32769).status_code == 413
    assert client.get("/workbench/review").status_code == 200


def test_comparison_tracks_config_and_manifest_resource_escalations(client):
    result = client.post(
        "/workbench/api/review",
        json={
            "config": payload(
                resources={"cpu_millis": 1000, "memory_mib": 128}, schedule="*/5 * * * *"
            ),
            "baseline": payload(),
        },
    ).json()["evidence"]
    comparison = result["comparison"]
    changes = {c["path"]: c for c in comparison["config_changes"]}
    assert changes["resources.cpu_millis"]["risk"] == "escalation"
    assert changes["resources.memory_mib"]["risk"] == "availability"
    assert changes["schedule"]["risk"] == "review"
    assert any("resources.requests.cpu" in c["path"] for c in comparison["manifest_changes"])
    assert comparison["escalations"] == 1
    assert not comparison["new_findings"]
    assert comparison["changed"]
    same = client.post(
        "/workbench/api/review", json={"config": payload(), "baseline": payload()}
    ).json()
    assert not same["evidence"]["comparison"]["changed"]


def test_structured_policy_cannot_be_fooled_by_safe_strings_in_annotations():
    from pipefoundry.manifest_review import audit_objects

    bundle = copy.deepcopy(objects(Pipeline.model_validate(payload()), 1))
    cron = bundle[1]
    pod = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    pod["automountServiceAccountToken"] = True
    pod["securityContext"]["runAsNonRoot"] = False
    container = pod["containers"][0]
    container["securityContext"]["allowPrivilegeEscalation"] = True
    container["securityContext"]["capabilities"] = {"drop": [], "add": ["SYS_ADMIN"]}
    container["resources"]["limits"] = {}
    cron["metadata"]["annotations"] = {"safe": "runAsNonRoot: true allowPrivilegeEscalation: false"}
    checks = {c["id"]: c for c in audit_objects(bundle)}
    for rule in (
        "service-account",
        "non-root",
        "privilege-escalation",
        "capabilities",
        "resources",
    ):
        assert checks[rule]["status"] == "fail"
        assert checks[rule]["evidence"]


def test_policy_inspects_all_containers_and_container_overrides():
    from pipefoundry.manifest_review import audit_objects

    bundle = objects(Pipeline.model_validate(payload()), 1)
    pod = bundle[1]["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    sidecar = copy.deepcopy(pod["containers"][0])
    sidecar["name"] = "sidecar"
    sidecar["securityContext"]["runAsUser"] = 0
    sidecar["securityContext"]["runAsNonRoot"] = False
    pod["initContainers"] = [sidecar]
    checks = {c["id"]: c for c in audit_objects(bundle)}
    assert checks["non-root"]["status"] == "fail"
    assert any("initContainers[0]" in e["path"] for e in checks["non-root"]["evidence"])


@pytest.mark.parametrize(
    ("path", "value", "rule"),
    [
        (("spec", "concurrencyPolicy"), "Allow", "concurrency"),
        (("spec", "startingDeadlineSeconds"), 0, "start-deadline"),
        (("spec", "jobTemplate", "spec", "activeDeadlineSeconds"), None, "job-deadline"),
        (
            (
                "spec",
                "jobTemplate",
                "spec",
                "template",
                "spec",
                "securityContext",
                "seccompProfile",
            ),
            {"type": "Unconfined"},
            "seccomp",
        ),
    ],
)
def test_policy_reports_actual_deadline_concurrency_and_seccomp_regressions(path, value, rule):
    from pipefoundry.manifest_review import audit_objects

    bundle = objects(Pipeline.model_validate(payload()), 1)
    target = bundle[1]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    checks = {c["id"]: c for c in audit_objects(bundle)}
    assert checks[rule]["status"] == "fail"
    assert any(e["value"] == value for e in checks[rule]["evidence"])


def test_comparison_flags_new_structured_policy_failures_and_yaml_hash():
    from pipefoundry.manifest_review import audit_objects, compare, snapshot

    baseline = snapshot(Pipeline.model_validate(payload()))
    current = copy.deepcopy(baseline)
    current["objects"][1]["spec"]["concurrencyPolicy"] = "Allow"
    current["checks"] = audit_objects(current["objects"])
    result = compare(baseline, current)
    assert result["new_findings"] == ["concurrency"]
    assert result["escalations"] == 1
    assert result["manifest_changes"][0]["after"] == "Allow"
    assert baseline["yaml_sha256"] == hashlib.sha256(baseline["manifest"].encode()).hexdigest()
