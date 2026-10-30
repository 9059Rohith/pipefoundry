"""Opt-in synthetic demo: real worker/SQL effects and bounded public receipts."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from pipefoundry.models import Pipeline

DEMO_NAME = "demo-orders"
DEMO_KEY = "synthetic-orders-v1"
DATES = ("2026-01-10", "2026-01-11")


def demo_ready(platform, *, key=DEMO_KEY):
    if not platform.durable:
        return False
    with platform.connect() as db:
        row = db.execute("SELECT completed FROM demo_seed WHERE seed_key=?", (key,)).fetchone()
    return bool(row and row[0])


def _config(name, schedule="0 0 * * *"):
    return Pipeline.model_validate(
        {
            "name": name,
            "schedule": schedule,
            "input": {"connector": "fixture"},
            "output": {"connector": "postgres"},
            "resources": {"cpu_millis": 100, "memory_mib": 128},
        }
    )


def seed_demo(platform, *, name=DEMO_NAME, key=DEMO_KEY):
    if not platform.durable:
        raise ValueError("public demo requires durable PostgreSQL metadata")
    config = _config(name)
    owner = uuid.uuid4().hex
    now = datetime.now(UTC)
    with platform.connect() as db:
        prior = db.execute("SELECT completed FROM demo_seed WHERE seed_key=?", (key,)).fetchone()
        acquired = db.execute(
            "INSERT INTO demo_seed(seed_key,pipeline_name,owner,lease_until,completed) "
            "VALUES(?,?,?,?,0) ON CONFLICT(seed_key) DO UPDATE "
            "SET owner=excluded.owner,lease_until=excluded.lease_until "
            "WHERE demo_seed.completed=0 AND demo_seed.lease_until<? RETURNING pipeline_name",
            (key, name, owner, (now + timedelta(minutes=5)).isoformat(), now.isoformat()),
        ).fetchone()
        if acquired is None:
            return bool(prior and prior[0])
        if acquired[0] != name:
            raise ValueError("demo seed key belongs to another pipeline")
    try:
        with platform.connect() as db:
            existing = db.execute(
                "SELECT config FROM revisions WHERE name=? ORDER BY revision DESC LIMIT 1", (name,)
            ).fetchone()
            cluster = db.execute(
                "SELECT COUNT(*) FROM cluster_targets WHERE name=? AND active=1", (name,)
            ).fetchone()[0]
            if existing:
                checked = Pipeline.model_validate_json(existing[0])
                if checked.input.connector != "fixture" or checked.output.connector != "postgres":
                    raise ValueError("demo name belongs to a non-synthetic pipeline")
            if cluster:
                raise ValueError("demo name belongs to a cluster pipeline")
            # Recover only expired synthetic-demo operations. Normal platform
            # locks never expire automatically; all demo writes are fixed upserts.
            if prior:
                removed = db.execute(
                    "DELETE FROM operations WHERE name=? AND started<?",
                    (name, (now - timedelta(minutes=5)).isoformat()),
                )
                if removed.rowcount:
                    stale = list(
                        db.execute(
                            "SELECT revision FROM revisions WHERE name=? "
                            "AND status IN ('running','rendering','deploying') "
                            "AND created<?",
                            (name, (now - timedelta(minutes=5)).isoformat()),
                        )
                    )
                    for revision in stale:
                        db.execute(
                            "UPDATE revisions SET status='failed' WHERE name=? AND revision=?",
                            (name, revision[0]),
                        )
                        db.execute(
                            "INSERT INTO audit(name,revision,action,outcome,created) "
                            "VALUES(?,?,'recover','interrupted',?)",
                            (name, revision[0], now.isoformat()),
                        )
        events = platform.audit(name)
        deployed = [
            event
            for event in events
            if event["action"] == "deploy" and event["outcome"] == "succeeded"
        ]
        if not deployed:
            platform.deploy(config)
            deployed = [
                event
                for event in platform.audit(name)
                if event["action"] == "deploy" and event["outcome"] == "succeeded"
            ]
        base_revision = deployed[0]["revision"]
        if len(deployed) < 2:
            platform.deploy(_config(name, "0 2 * * *"))
        events = platform.audit(name)
        if not any(
            event["action"] == "backfill" and event["outcome"] == "succeeded" for event in events
        ):
            if platform.status(name)["status"] != "succeeded":
                platform.deploy(_config(name, "0 2 * * *"))
            platform.backfill(name, *DATES)
        if not any(
            event["action"] == "rollback" and event["outcome"] == "succeeded"
            for event in platform.audit(name)
        ):
            platform.rollback(name, base_revision)
        with platform.connect() as db:
            committed = db.execute(
                "UPDATE demo_seed SET completed=1,last_error='' WHERE seed_key=? AND owner=? "
                "RETURNING completed",
                (key, owner),
            ).fetchone()
        return bool(committed and committed[0])
    except Exception as exc:
        with platform.connect() as db:
            db.execute(
                "UPDATE demo_seed SET lease_until=?,last_error=? WHERE seed_key=? AND owner=?",
                (datetime.now(UTC).isoformat(), type(exc).__name__, key, owner),
            )
        raise


def _result(platform, name, revision, filename):
    with platform.connect() as db:
        row = db.execute(
            "SELECT contents FROM artifacts WHERE name=? AND revision=? AND path=?",
            (name, revision, filename),
        ).fetchone()
    if not row or len(row[0]) > 131072:
        raise ValueError("demo workload receipt is unavailable")
    result = json.loads(bytes(row[0]))
    # Deliberately exclude total table counts and source records: other private
    # pipelines can use the same sink, and their data must never become public.
    return {"rows": int(result["rows"]), "invalid_rows": int(result["quality"]["invalid_rows"])}


def demo_receipt(platform, *, name=DEMO_NAME, key=DEMO_KEY):
    if not demo_ready(platform, key=key):
        raise ValueError("demo is not initialized")
    state = platform.status(name)
    config = platform.config(name)
    if config.input.connector != "fixture" or config.output.connector != "postgres":
        raise ValueError("public demo is not a synthetic pipeline")
    events = platform.audit(name)
    backfill = next(
        event
        for event in reversed(events)
        if event["action"] == "backfill" and event["outcome"] == "succeeded"
    )
    with platform.connect() as db:
        checksum = db.execute(
            "SELECT checksum FROM revisions WHERE name=? AND revision=?", (name, state["revision"])
        ).fetchone()[0]
        count = db.execute(
            "SELECT COUNT(*) FROM artifacts WHERE name=? AND revision=?", (name, state["revision"])
        ).fetchone()[0]
    return {
        "service": "PipeFoundry",
        "read_only": True,
        "data_source": "synthetic fixtures executed by a real Python worker and PostgreSQL",
        "execution_mode": "on-demand; cron artifacts are rendered but not scheduled by this host",
        "pipeline": {
            **{
                field: state[field]
                for field in ("name", "revision", "status", "executor", "created")
            },
            "schedule": config.schedule,
        },
        "workload": _result(platform, name, state["revision"], "run-latest.log"),
        "backfill": [
            {"date": day, **_result(platform, name, backfill["revision"], f"run-{day}.log")}
            for day in DATES
        ],
        "artifact": {"sha256": checksum, "files": count, "storage": "PostgreSQL BYTEA"},
        "events": [
            {field: event[field] for field in ("revision", "action", "outcome", "created")}
            for event in events[-8:]
        ],
        "observed_at": datetime.now(UTC).isoformat(),
    }
