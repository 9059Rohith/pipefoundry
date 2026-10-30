"""Acceptance check against an actual running API and its PostgreSQL connector."""

import json
import os

import httpx

token = os.environ["PIPEFOUNDRY_API_TOKEN"]
base = os.environ.get("PIPEFOUNDRY_API_URL", "http://127.0.0.1:8094")
headers = {"Authorization": f"Bearer {token}"}
config = {
    "name": "compose-smoke",
    "schedule": "0 * * * *",
    "input": {"connector": "fixture"},
    "output": {"connector": "postgres"},
}
with httpx.Client(base_url=base, timeout=120, trust_env=False) as client:
    assert client.get("/health/ready").status_code == 200
    assert client.get("/pipelines").status_code == 401
    deployed = client.post("/pipelines", headers=headers, json={"config": config})
    deployed.raise_for_status()
    assert deployed.json()["status"] == "succeeded"
    revision = deployed.json()["revision"]
    duplicate = client.post("/pipelines", headers=headers, json={"config": config})
    duplicate.raise_for_status()
    assert duplicate.json()["revision"] == revision + 1
    logs = client.get("/pipelines/compose-smoke/logs", headers=headers)
    logs.raise_for_status()
    assert '"invalid_rows": 0' in "".join(logs.json()["logs"])
    backfill = client.post(
        "/pipelines/compose-smoke/backfill",
        headers=headers,
        json={"start": "2026-01-10", "end": "2026-01-11"},
    )
    backfill.raise_for_status()
    assert backfill.json()["partitions"] == 2
    rolled = client.post(
        "/pipelines/compose-smoke/rollback", headers=headers, json={"revision": revision}
    )
    rolled.raise_for_status()
    assert rolled.json()["revision"] == revision + 2
    deleted = client.delete("/pipelines/compose-smoke", headers=headers)
    deleted.raise_for_status()
    assert deleted.json()["status"] == "torn_down"
    audit = client.get("/pipelines/compose-smoke/audit", headers=headers)
    audit.raise_for_status()
    print(
        json.dumps(
            {
                "api": "real HTTP",
                "sink": "real PostgreSQL",
                "deployment": deployed.json(),
                "backfill": backfill.json(),
                "rollback": rolled.json(),
                "teardown": deleted.json(),
                "audit_events": len(audit.json()["events"]),
            },
            indent=2,
        )
    )
