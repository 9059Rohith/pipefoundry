import hashlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "a" * 40)
    monkeypatch.setenv("PIPEFOUNDRY_SEED_DEMO", "false")
    from pipefoundry.api import create_app

    with TestClient(create_app(tmp_path)) as client:
        yield client


def payload(**changes):
    return {
        "config": {"name": "orders-hourly", "schedule": "0 * * * *"},
        "partition": "2026-11-09",
        "rows": [
            {"id": "a", "amount_cents": 100, "currency": "usd"},
            {"id": "b", "amount_cents": 700, "currency": "eur"},
            {"id": "a", "amount_cents": 250, "currency": "Usd"},
        ],
        **changes,
    }


def test_rehearsal_matches_runtime_dedup_and_currency_totals_without_side_effects(
    client, tmp_path, monkeypatch
):
    # Fetching a configured connector or writing output would break this contract.
    from pipefoundry import workloads

    def forbidden(*args, **kwargs):
        pytest.fail("sample rehearsal invoked a connector or output writer")

    monkeypatch.setattr(workloads, "fetch_orders", forbidden)
    monkeypatch.setattr(workloads, "ingest", forbidden)
    monkeypatch.setattr(workloads, "ingest_postgres", forbidden)
    before = list(tmp_path.rglob("*"))
    body = payload()
    body["config"]["input"] = {"connector": "orders_api"}
    response = client.post("/workbench/api/rehearsal", json=body)
    assert response.status_code == 200
    report = response.json()["evidence"]
    assert report["accepted"] is True
    assert report["summary"] == {
        "input_rows": 3,
        "output_rows": 2,
        "replaced_rows": 1,
        "currency_normalizations": 3,
    }
    assert report["normalized_rows"] == [
        {"partition_date": "2026-11-09", "id": "a", "amount_cents": 250, "currency": "USD"},
        {"partition_date": "2026-11-09", "id": "b", "amount_cents": 700, "currency": "EUR"},
    ]
    assert report["currency_totals"] == [
        {"currency": "EUR", "rows": 1, "amount_cents": 700},
        {"currency": "USD", "rows": 1, "amount_cents": 250},
    ]
    assert report["duplicates"] == [{"id": "a", "source_rows": [1, 3], "winner_row": 3}]
    assert "kind: CronJob" in report["manifest"]
    assert json.loads(report["config_json"])["input"]["connector"] == "orders_api"
    assert before == list(tmp_path.rglob("*"))
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert response.json()["evidence_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert response.json() == client.post("/workbench/api/rehearsal", json=body).json()
    assert client.post("/pipelines", json={"config": body["config"]}).status_code == 401


def test_rehearsal_rejects_whole_batch_with_safe_row_diagnostics(client):
    body = payload(
        rows=[
            {"id": "ok", "amount_cents": 1, "currency": "usd"},
            {"id": "SECRET-MARKER", "amount_cents": -1, "currency": "US"},
            {
                "id": "<script>SECRET-MARKER</script>",
                "amount_cents": True,
                "currency": "usd",
                "SECRET-MARKER": "SECRET-MARKER",
            },
        ]
    )
    response = client.post("/workbench/api/rehearsal", json=body)
    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert evidence["accepted"] is False
    assert evidence["normalized_rows"] == []
    assert evidence["currency_totals"] == []
    assert evidence["summary"]["output_rows"] == 0
    fields = {(issue["row"], issue["field"]) for issue in evidence["issues"]}
    assert fields == {
        (2, "amount_cents"),
        (2, "currency"),
        (3, "id"),
        (3, "amount_cents"),
        (3, "unknown field"),
    }
    assert "SECRET-MARKER" not in response.text


@pytest.mark.parametrize(
    "changes",
    [
        {"rows": []},
        {"rows": [{}] * 101},
        {"rows": ["SECRET-MARKER"]},
        {"partition": "2026-02-30"},
        {"partition": "20261109"},
        {
            "config": {
                "name": "orders",
                "schedule": "0 * * * *",
                "output": {"path": "../SECRET-MARKER"},
            }
        },
        {"config": {"name": "orders", "schedule": "0 * * * *", "SECRET-MARKER": "x"}},
        {
            "config": {
                "name": "spark",
                "schedule": "0 * * * *",
                "input": {"connector": "spark_json"},
                "output": {"connector": "parquet"},
                "resources": {"memory_mib": 1024},
            }
        },
        {"SECRET-MARKER": "x"},
    ],
)
def test_rehearsal_bounds_and_unsafe_inputs_are_sanitized(client, changes):
    response = client.post("/workbench/api/rehearsal", json=payload(**changes))
    assert response.status_code == 422
    assert "SECRET-MARKER" not in response.text


def test_rehearsal_body_limit_and_public_page(client):
    assert client.post("/workbench/api/rehearsal", content=b"x" * 32769).status_code == 413
    response = client.get("/workbench/rehearsal")
    assert response.status_code == 200
    assert 'data-page="rehearsal"' in response.text
    assert 'data-nav="rehearsal"' in response.text


def test_rehearsal_issue_count_is_bounded_and_missing_fields_are_diagnosed(client):
    response = client.post("/workbench/api/rehearsal", json=payload(rows=[{}] * 100))
    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert len(evidence["issues"]) == 100
    assert evidence["issues_truncated"] is True
    assert evidence["invalid_rows"] == 100
