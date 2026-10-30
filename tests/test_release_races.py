"""Independent processes and real workers verify lease scope and launch uniqueness."""

import json
import os
import subprocess
import sys
import threading
import uuid

import pytest

from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline
from pipefoundry.releases import ReleaseSentinel

DSN = os.environ.get("PIPEFOUNDRY_POSTGRES_DSN")


@pytest.fixture(params=["sqlite", "postgres"])
def service(request, tmp_path):
    if request.param == "postgres" and not DSN:
        pytest.skip("PostgreSQL DSN required")
    dsn = DSN if request.param == "postgres" else None
    return ReleaseSentinel(Platform(tmp_path / "state", metadata_dsn=dsn))


def desired(service):
    return Pipeline.model_validate(
        {
            "name": "race-" + uuid.uuid4().hex[:12],
            "schedule": "0 * * * *",
            "output": {"connector": "postgres" if service.platform.durable else "sqlite"},
        }
    )


@pytest.mark.parametrize("same_key", [False, True])
def test_two_process_race_launches_one_revision_and_one_worker(service, tmp_path, same_key):
    config = desired(service)
    plan = service.plan(config)
    gate = tmp_path / "gate"
    program = """
import json,os,sys,time
from pathlib import Path
from pipefoundry.engine import Platform
from pipefoundry.releases import ReleaseSentinel
state,gate,plan_id,digest,key=sys.argv[1:]
while not Path(gate).exists(): time.sleep(.01)
service=ReleaseSentinel(Platform(state,metadata_dsn=os.environ.get("RACE_METADATA_DSN")))
execute=service.platform._execute
def observed_execute(*args,**kwargs):
    marker=os.open(str(Path(gate).with_suffix('.launches')),os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
    try: os.write(marker,b'worker\\n')
    finally: os.close(marker)
    return execute(*args,**kwargs)
service.platform._execute=observed_execute
try:
    result=service.apply(plan_id,digest,key)
except ValueError as exc:
    result={"error":str(exc)}
print(json.dumps(result))
"""
    environment = os.environ.copy()
    environment.pop("PIPEFOUNDRY_METADATA_DSN", None)
    if service.platform.durable:
        environment["RACE_METADATA_DSN"] = DSN
    children = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                program,
                str(service.platform.root),
                str(gate),
                plan["plan_id"],
                plan["digest"],
                config.name + "-key-" + str(0 if same_key else index),
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(2)
    ]
    gate.touch()
    results = []
    for child in children:
        output, errors = child.communicate(timeout=60)
        assert child.returncode == 0, errors
        results.append(json.loads(output))
    assert sum(result.get("state") == "succeeded" for result in results) >= 1, results
    if not same_key:
        assert sum("error" in result for result in results) == 1
    assert gate.with_suffix(".launches").read_text().splitlines() == ["worker"]
    assert service.platform.status(config.name)["revision"] == 1
    assert len(service.platform.audit(config.name)) == 1
    with service.platform.connect() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM release_receipts WHERE name=?", (config.name,)
            ).fetchone()[0]
            == 1
        )


def test_apply_retains_lease_without_db_transaction_while_real_worker_runs(service, monkeypatch):
    config = desired(service)
    plan = service.plan(config)
    original = service.platform._execute
    observed = threading.Event()

    def execute(args, log, timeout):
        other = Platform(service.platform.root, metadata_dsn=service.platform._metadata_dsn)
        with pytest.raises(ValueError, match="active operation"):
            with other.operation(config.name):
                pytest.fail("release lost exclusivity before worker launch")
        # A separate database writer must not be blocked behind execution's transaction.
        with other.operation("independent-pipeline"):
            observed.set()
        return original(args, log, timeout)

    monkeypatch.setattr(service.platform, "_execute", execute)
    receipt = service.apply(plan["plan_id"], plan["digest"], config.name + "-lease")
    assert receipt["state"] == "succeeded"
    assert observed.is_set()


def test_postgres_plan_survives_cold_scratch_root(service, tmp_path):
    if not service.platform.durable:
        pytest.skip("cold scratch roots require durable metadata")
    config = desired(service)
    plan = service.plan(config)
    cold = ReleaseSentinel(Platform(tmp_path / "cold", metadata_dsn=DSN))
    assert cold.get_plan(plan["plan_id"], plan["digest"]) == plan
    key = config.name + "-cold"
    result = cold.apply(plan["plan_id"], plan["digest"], key)
    assert result["state"] == "succeeded"
    third = ReleaseSentinel(Platform(tmp_path / "third", metadata_dsn=DSN))
    assert third.apply(plan["plan_id"], plan["digest"], key) == result
    assert third.plan(config)["operation"] == "no-op"


def test_demo_auto_recovery_cannot_steal_a_protected_release_lease(service):
    if not service.platform.durable:
        pytest.skip("demo recovery requires PostgreSQL")
    from datetime import UTC, datetime, timedelta

    from pipefoundry.demo import seed_demo

    config = desired(service)
    plan = service.plan(config)
    past = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    key = config.name + "-seed"
    with service.platform.connect() as db:
        db.execute("INSERT INTO operations VALUES(?,?)", (config.name, past))
        db.execute("INSERT INTO demo_seed VALUES(?,?,?,?,0,'')", (key, config.name, "prior", past))
    try:
        with pytest.raises(ValueError, match="active operation"):
            seed_demo(service.platform, name=config.name, key=key)
        with service.platform.connect() as db:
            assert (
                db.execute(
                    "SELECT started FROM operations WHERE name=?", (config.name,)
                ).fetchone()[0]
                == past
            )
        assert service.get_plan(plan["plan_id"], plan["digest"]) == plan
    finally:
        with service.platform.connect() as db:
            db.execute("DELETE FROM operations WHERE name=?", (config.name,))
