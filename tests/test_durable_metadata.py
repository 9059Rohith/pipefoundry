import os
import uuid

import pytest

from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline

DSN = os.environ.get("PIPEFOUNDRY_POSTGRES_DSN")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(not DSN, reason="PostgreSQL DSN required")]


def pipeline():
    return Pipeline.model_validate(
        {
            "name": "durable-" + uuid.uuid4().hex[:12],
            "schedule": "0 * * * *",
            "input": {"connector": "fixture"},
            "output": {"connector": "postgres"},
        }
    )


def test_preview_reads_postgres_metadata_from_cold_root_without_restoring_artifacts(tmp_path):
    config = pipeline()
    first = Platform(tmp_path / "first", metadata_dsn=DSN)
    first.deploy(config)
    second = Platform(tmp_path / "cold", metadata_dsn=DSN)

    def counts():
        with second.connect() as db:
            return [
                db.execute(f"SELECT COUNT(*) FROM {table} WHERE name=?", (config.name,)).fetchone()[
                    0
                ]
                for table in ("revisions", "audit", "operations", "artifacts")
            ]

    before = counts()
    assert second.preview(config)["action"] == "no-op"
    changed = config.model_copy(update={"schedule": "30 2 * * *"})
    assert second.preview(changed)["changes"] == [{"path": "config.schedule", "kind": "changed"}]
    assert counts() == before
    assert list((tmp_path / "cold").iterdir()) == []
    assert second.status(config.name)["revision"] == 1


def test_postgres_preview_empty_revision_is_one_statement_and_has_no_durable_effects(
    tmp_path, monkeypatch
):
    from pipefoundry.metadata import PostgresConnection

    config = pipeline()
    platform = Platform(tmp_path, metadata_dsn=DSN)
    statements = []
    original = PostgresConnection.execute

    def tracked(db, statement, parameters=()):
        statements.append(statement)
        return original(db, statement, parameters)

    monkeypatch.setattr(PostgresConnection, "execute", tracked)
    result = platform.preview(config)
    assert result["action"] == "create"
    assert result["current"] is None
    assert len(statements) == 1
    assert statements[0].startswith("SELECT")
    with platform.connect() as db:
        for table in ("revisions", "audit", "operations", "artifacts"):
            assert (
                db.execute(f"SELECT COUNT(*) FROM {table} WHERE name=?", (config.name,)).fetchone()[
                    0
                ]
                == 0
            )
    assert list(tmp_path.iterdir()) == []


def test_postgres_state_artifacts_logs_and_rollback_survive_fresh_scratch_roots(tmp_path):
    config = pipeline()
    first = Platform(tmp_path / "first", metadata_dsn=DSN)
    assert first.deploy(config)["status"] == "succeeded"
    second = Platform(tmp_path / "second", metadata_dsn=DSN)
    assert second.status(config.name)["revision"] == 1
    assert second.config(config.name) == config
    assert second.logs(config.name) and '"invalid_rows": 0' in second.logs(config.name)[0]
    assert (tmp_path / "second/revisions" / config.name / "1/checksums.json").is_file()
    assert second.backfill(config.name, "2026-08-11", "2026-08-12")["partitions"] == 2
    assert second.rollback(config.name, 1)["revision"] == 2
    third = Platform(tmp_path / "third", metadata_dsn=DSN)
    assert third.config(config.name) == config
    assert [event["action"] for event in third.audit(config.name)] == [
        "deploy",
        "backfill",
        "rollback",
    ]
    assert third.teardown(config.name)["status"] == "torn_down"


def test_postgres_mutation_lock_spans_independent_platforms(tmp_path):
    config = pipeline()
    first = Platform(tmp_path / "first", metadata_dsn=DSN)
    second = Platform(tmp_path / "second", metadata_dsn=DSN)
    with first.operation(config.name):
        with pytest.raises(ValueError, match="active operation"):
            second.deploy(config)
    assert second.deploy(config)["status"] == "succeeded"


def test_hosted_local_execution_rejects_ephemeral_data_outputs(tmp_path):
    platform = Platform(tmp_path, metadata_dsn=DSN)
    config = pipeline().model_copy(
        update={
            "output": Pipeline.model_validate({"name": "unused", "schedule": "0 * * * *"}).output
        }
    )
    with pytest.raises(ValueError, match="PostgreSQL output"):
        platform.deploy(config)


def test_corrupt_stored_artifact_cannot_escape_rehydration_root(tmp_path):
    import psycopg

    config = pipeline()
    Platform(tmp_path / "first", metadata_dsn=DSN).deploy(config)
    with psycopg.connect(DSN) as db:
        db.execute(
            "INSERT INTO pf_artifacts(name,revision,path,contents) VALUES(%s,1,%s,%s)",
            (config.name, "../../escape", b"forbidden"),
        )
    restored = Platform(tmp_path / "second", metadata_dsn=DSN)
    with pytest.raises(ValueError):
        restored.config(config.name)
    assert not (tmp_path / "escape").exists()


def test_synthetic_demo_seed_is_real_idempotent_and_survives_restart(tmp_path):
    from pipefoundry.demo import demo_receipt, seed_demo

    name, key = "demo-" + uuid.uuid4().hex[:12], uuid.uuid4().hex
    first = Platform(tmp_path / "first", metadata_dsn=DSN)
    assert seed_demo(first, name=name, key=key)
    receipt = demo_receipt(first, name=name, key=key)
    assert receipt["pipeline"]["status"] == "succeeded"
    assert receipt["pipeline"]["revision"] == 3
    assert receipt["pipeline"]["schedule"] == "0 0 * * *"
    assert receipt["workload"] == {"rows": 3, "invalid_rows": 0}
    assert [partition["rows"] for partition in receipt["backfill"]] == [3, 3]
    assert [event["action"] for event in receipt["events"]] == [
        "deploy",
        "deploy",
        "backfill",
        "rollback",
    ]
    restarted = Platform(tmp_path / "fresh", metadata_dsn=DSN)
    assert seed_demo(restarted, name=name, key=key)
    assert len(restarted.audit(name)) == 4
    assert demo_receipt(restarted, name=name, key=key)["artifact"]["sha256"]


def test_demo_seed_recovers_real_failed_worker_without_fabricating_success(tmp_path, monkeypatch):
    from pipefoundry.demo import demo_receipt, seed_demo

    name, key = "demo-" + uuid.uuid4().hex[:12], uuid.uuid4().hex
    platform = Platform(tmp_path, metadata_dsn=DSN)
    monkeypatch.setenv("PIPEFOUNDRY_POSTGRES_DSN", "postgresql://invalid@127.0.0.1:1/invalid")
    with pytest.raises(RuntimeError):
        seed_demo(platform, name=name, key=key)
    with pytest.raises(ValueError, match="not initialized"):
        demo_receipt(platform, name=name, key=key)
    monkeypatch.setenv("PIPEFOUNDRY_POSTGRES_DSN", DSN)
    assert seed_demo(platform, name=name, key=key)
    assert demo_receipt(platform, name=name, key=key)["workload"]["rows"] == 3
    assert platform.audit(name)[0]["outcome"] == "failed"


def test_public_demo_endpoints_do_not_expose_private_api_or_credentials(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from pipefoundry.api import create_app

    monkeypatch.setenv("PIPEFOUNDRY_METADATA_DSN", DSN)
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "t" * 32)
    monkeypatch.setenv("PIPEFOUNDRY_PUBLIC_DEMO", "1")
    name, key = "demo-" + uuid.uuid4().hex[:12], uuid.uuid4().hex
    with TestClient(create_app(tmp_path, demo_name=name, demo_key=key)) as client:
        assert client.post("/demo/seed").status_code == 401
        assert client.get("/pipelines").status_code == 401
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            response = client.get("/demo")
            if response.status_code == 200:
                break
            time.sleep(0.1)
        assert response.status_code == 200, response.text
        assert response.json()["read_only"] is True
        assert DSN not in response.text and "t" * 32 not in response.text
        console = client.get("/")
        assert "text/html" in console.headers["content-type"]
        assert name in console.text and "Pipeline execution" in console.text
        assert "script-src" not in console.text and "<script" not in console.text
        assert "default-src 'none'" in console.headers["content-security-policy"]
        assert client.post("/pipelines", json={}).status_code == 401


def test_persistent_revision_artifact_budget_blocks_new_files_but_allows_log_updates(
    tmp_path, monkeypatch
):
    import pipefoundry.engine as engine

    monkeypatch.setattr(engine, "MAX_REVISION_ARTIFACTS", 12, raising=False)
    config = pipeline()
    platform = Platform(tmp_path, metadata_dsn=DSN)
    platform.deploy(config)
    directory = platform.revision_dir(config.name, 1)
    for index in range(3):
        platform._write_log(directory / f"quota-{index}.log", "bounded")
    with pytest.raises(ValueError, match="artifact limit"):
        platform._write_log(directory / "quota-overflow.log", "rejected")
    assert not (directory / "quota-overflow.log").exists()
    platform._write_log(directory / "quota-0.log", "updated")
    with platform.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM artifacts WHERE name=?", (config.name,)).fetchone()[0]
            == 12
        )


def test_demo_recovers_only_expired_synthetic_seed_and_records_interruption(tmp_path):
    from datetime import UTC, datetime, timedelta

    from pipefoundry.demo import seed_demo

    name, key = "demo-" + uuid.uuid4().hex[:12], uuid.uuid4().hex
    platform = Platform(tmp_path, metadata_dsn=DSN)
    config = Pipeline.model_validate(
        {
            "name": name,
            "schedule": "0 0 * * *",
            "input": {"connector": "fixture"},
            "output": {"connector": "postgres"},
        }
    )
    past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    with platform.connect() as db:
        db.execute(
            "INSERT INTO revisions VALUES(?,1,?,'running','local',?,'')",
            (name, config.model_dump_json(), past),
        )
        db.execute("INSERT INTO operations VALUES(?,?)", (name, past))
        db.execute("INSERT INTO demo_seed VALUES(?,?,?, ?,0,'')", (key, name, "old-owner", past))
    assert seed_demo(platform, name=name, key=key)
    with platform.connect() as db:
        assert (
            db.execute(
                "SELECT status FROM revisions WHERE name=? AND revision=1", (name,)
            ).fetchone()[0]
            == "failed"
        )
    assert platform.audit(name)[0]["action"] == "recover"
    assert platform.status(name)["status"] == "succeeded"


def test_postgres_schema_initialization_holds_a_transaction_lock(tmp_path, monkeypatch):
    import psycopg

    import pipefoundry.engine as engine
    from pipefoundry.metadata import PostgresConnection

    original = PostgresConnection.executescript
    observed = []

    def inspect_real_lock(connection, script):
        with psycopg.connect(DSN) as other:
            acquired = other.execute(
                "SELECT pg_try_advisory_xact_lock(%s,1)",
                (getattr(engine, "METADATA_SCHEMA_LOCK", 1346785350),),
            ).fetchone()[0]
        observed.append(acquired)
        assert acquired is False
        return original(connection, script)

    monkeypatch.setattr(PostgresConnection, "executescript", inspect_real_lock)
    Platform(tmp_path, metadata_dsn=DSN)
    assert observed == [False]
