"""Guarded release contracts exercise real metadata, rendering and local workers."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline


def config(**changes):
    return Pipeline.model_validate({"name": "sentinel-orders", "schedule": "0 * * * *", **changes})


def sentinel(tmp_path):
    from pipefoundry.releases import ReleaseSentinel

    return ReleaseSentinel(Platform(tmp_path))


def test_plan_is_durable_canonical_and_contains_no_operator_secrets(tmp_path, monkeypatch):
    service = sentinel(tmp_path)
    monkeypatch.setenv("PIPEFOUNDRY_POSTGRES_DSN", "postgresql://private-secret@invalid/db")
    first = service.plan(config())
    second = service.plan(config(schedule="0  * * * *"))
    assert first["desired_fingerprint"] == second["desired_fingerprint"]
    assert first["operation"] == "create"
    assert first["expected"] is None
    assert first["risk"]["input_rows_upper_bound"] == 3
    assert first["risk"]["backfill_partitions"] == 0
    assert "private-secret" not in json.dumps(first)
    assert not (tmp_path / "revisions").exists()
    assert sentinel(tmp_path).get_plan(first["plan_id"], first["digest"]) == first
    unsigned = {key: value for key, value in first.items() if key != "digest"}
    assert (
        hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        == first["digest"]
    )


@pytest.mark.parametrize(
    "policy",
    [
        {"allowed_operation": "update"},
        {"max_cpu_millis": 100},
        {"max_memory_mib": 64},
        {"max_input_rows": 2},
    ],
)
def test_policy_denies_release_before_revision_creation(tmp_path, policy):
    from pipefoundry.release_models import RolloutPolicy

    service = sentinel(tmp_path)
    with pytest.raises(ValueError, match="policy"):
        service.plan(config(), policy=RolloutPolicy(**policy))
    assert service.platform.list() == []


def test_stored_plan_tampering_and_wrong_digest_are_rejected(tmp_path):
    service = sentinel(tmp_path)
    plan = service.plan(config())
    with pytest.raises(ValueError, match="identity"):
        service.get_plan(plan["plan_id"], "0" * 64)
    with service.platform.connect() as db:
        payload = json.loads(db.execute("SELECT payload FROM release_plans").fetchone()[0])
        payload["policy"]["max_input_rows"] = 1
        db.execute("UPDATE release_plans SET payload=?", (json.dumps(payload),))
    with pytest.raises(ValueError, match="integrity"):
        service.get_plan(plan["plan_id"], plan["digest"])


def test_apply_is_idempotent_even_after_plan_expiry(tmp_path, monkeypatch):
    service = sentinel(tmp_path)
    plan = service.plan(config())
    receipt = service.apply(plan["plan_id"], plan["digest"], "release-001")
    assert receipt["state"] == "succeeded"
    assert receipt["revision"] == 1
    monkeypatch.setattr(service, "now", lambda: datetime.now(UTC) + timedelta(days=1))
    assert service.apply(plan["plan_id"], plan["digest"], "release-001") == receipt
    assert service.platform.status(config().name)["revision"] == 1
    assert len(service.platform.audit(config().name)) == 1


def test_expired_plan_does_not_allocate_work(tmp_path, monkeypatch):
    service = sentinel(tmp_path)
    plan = service.plan(config(), ttl_seconds=1)
    monkeypatch.setattr(service, "now", lambda: datetime.now(UTC) + timedelta(seconds=2))
    with pytest.raises(ValueError, match="expired"):
        service.apply(plan["plan_id"], plan["digest"], "expired-001")
    assert service.platform.list() == []


def test_legacy_deploy_and_status_changes_invalidate_plan(tmp_path):
    service = sentinel(tmp_path)
    plan = service.plan(config())
    service.platform.deploy(config())
    with pytest.raises(ValueError, match="stale"):
        service.apply(plan["plan_id"], plan["digest"], "stale-001")
    plan = service.plan(config())
    service.platform._set_status(config().name, 1, "failed")
    with pytest.raises(ValueError, match="stale"):
        service.apply(plan["plan_id"], plan["digest"], "stale-002")


def test_operator_drift_rejects_without_exposing_credentials(tmp_path, monkeypatch):
    service = sentinel(tmp_path)
    plan = service.plan(config())
    monkeypatch.setenv("PIPEFOUNDRY_WORKER_IMAGE", "registry/secret-token:changed")
    with pytest.raises(ValueError, match="operator settings changed") as exc:
        service.apply(plan["plan_id"], plan["digest"], "drift-001")
    assert "secret-token" not in str(exc.value)


def test_libpq_operator_environment_drift_is_bound(tmp_path, monkeypatch):
    service = sentinel(tmp_path)
    plan = service.plan(config())
    monkeypatch.setenv("PGOPTIONS", "-c search_path=private-sentinel")
    with pytest.raises(ValueError, match="operator settings changed") as exc:
        service.apply(plan["plan_id"], plan["digest"], "libpq-drift-001")
    assert "private-sentinel" not in str(exc.value)


def test_current_artifact_mutation_invalidates_noop(tmp_path):
    service = sentinel(tmp_path)
    service.platform.deploy(config())
    plan = service.plan(config())
    assert plan["operation"] == "no-op"
    path = service.platform.revision_dir(config().name, 1) / "pipeline.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="stale"):
        service.apply(plan["plan_id"], plan["digest"], "artifact-001")


def test_noop_records_receipt_without_new_revision_or_worker(tmp_path):
    service = sentinel(tmp_path)
    service.platform.deploy(config())
    plan = service.plan(config())
    receipt = service.apply(plan["plan_id"], plan["digest"], "noop-001")
    assert receipt["operation"] == "no-op"
    assert receipt["revision"] == 1
    assert service.platform.status(config().name)["revision"] == 1
    assert len(service.platform.audit(config().name)) == 1


def test_failed_worker_is_terminal_and_new_plan_is_required(tmp_path, monkeypatch):
    service = sentinel(tmp_path)
    desired = config(output={"connector": "postgres"})
    monkeypatch.setenv("PIPEFOUNDRY_POSTGRES_DSN", "postgresql://private-secret@127.0.0.1:1/db")
    plan = service.plan(desired)
    receipt = service.apply(plan["plan_id"], plan["digest"], "failed-001")
    assert receipt["state"] == "failed"
    assert "private-secret" not in json.dumps(receipt)
    assert service.apply(plan["plan_id"], plan["digest"], "failed-001") == receipt
    assert service.platform.status(desired.name)["revision"] == 1
    recovered = service.recover("failed-001", confirm_worker_stopped=True)
    assert recovered["state"] == "failed"
    assert service.platform.status(desired.name)["status"] == "failed"
    # Correct the output configuration and review a separate update; never
    # repurpose the failed receipt or silently retry its worker.
    replacement = service.plan(config())
    assert replacement["operation"] == "update"
    success = service.apply(replacement["plan_id"], replacement["digest"], "fixed-worker-001")
    assert success["state"] == "succeeded" and success["revision"] == 2
    assert service.receipt("failed-001") == recovered


def test_idempotency_key_cannot_be_rebound_or_plan_replayed_under_another_key(tmp_path):
    service = sentinel(tmp_path)
    first = service.plan(config())
    service.apply(first["plan_id"], first["digest"], "bound-001")
    second = service.plan(config())
    with pytest.raises(ValueError, match="idempotency"):
        service.apply(second["plan_id"], second["digest"], "bound-001")
    with pytest.raises(ValueError, match="already applied"):
        service.apply(first["plan_id"], first["digest"], "bound-002")


def test_plan_after_operator_change_requires_update_even_when_config_is_equal(
    tmp_path, monkeypatch
):
    service = sentinel(tmp_path)
    service.platform.deploy(config())
    monkeypatch.setenv("PIPEFOUNDRY_NAMESPACE", "changed-target")
    assert service.plan(config())["operation"] == "update"


def test_plan_after_worker_code_change_requires_update(tmp_path, monkeypatch):
    service = sentinel(tmp_path)
    service.platform.deploy(config())
    monkeypatch.setattr(type(service), "_code_identity", staticmethod(lambda: "a" * 64))
    assert service.plan(config())["operation"] == "update"


def test_crashed_attempt_retry_does_not_launch_and_recovery_closes_reserved_revision(
    tmp_path, monkeypatch
):
    service = sentinel(tmp_path)
    plan = service.plan(config())

    def interrupted(*args):
        raise SystemExit("simulated controller termination")

    monkeypatch.setattr(service, "_execute_reserved", interrupted)
    with pytest.raises(SystemExit):
        service.apply(plan["plan_id"], plan["digest"], "crashed-001")
    receipt = sentinel(tmp_path).apply(plan["plan_id"], plan["digest"], "crashed-001")
    assert receipt["state"] == "executing"
    assert receipt["revision"] == 1
    assert service.platform.status(config().name)["status"] == "rendering"
    with pytest.raises(ValueError, match="confirmation"):
        service.recover("crashed-001", confirm_worker_stopped=False)
    receipt = service.recover("crashed-001", confirm_worker_stopped=True)
    assert receipt["state"] == "failed"
    assert receipt["error_code"] == "interrupted"
    replacement = sentinel(tmp_path).plan(config())
    assert replacement["operation"] == "update"


def test_failed_materialization_with_partial_files_can_be_replanned(tmp_path, monkeypatch):
    import pipefoundry.engine as engine

    service = sentinel(tmp_path)
    plan = service.plan(config())
    original = engine.render

    def interrupted_render(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("interrupted after writing files, before metadata commit")

    with monkeypatch.context() as patch:
        patch.setattr(engine, "render", interrupted_render)
        receipt = service.apply(plan["plan_id"], plan["digest"], "partial-render-001")
    assert receipt["state"] == "failed"
    replacement = service.plan(config())
    assert replacement["operation"] == "update"
    result = service.apply(replacement["plan_id"], replacement["digest"], "partial-render-002")
    assert result["state"] == "succeeded" and result["revision"] == 2
