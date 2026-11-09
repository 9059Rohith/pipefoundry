import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "a" * 40)
    monkeypatch.setenv("PIPEFOUNDRY_SEED_DEMO", "false")
    from pipefoundry.api import create_app

    with TestClient(create_app(tmp_path)) as client:
        yield client


def test_retained_sample_maps_actual_pinned_fares_and_carries_export_provenance(client):
    response = client.get("/workbench/api/rehearsal/sample")
    assert response.status_code == 200
    sample = response.json()
    provenance = sample["provenance"]
    assert provenance["source_sha256"] == (
        "942e7b07bf180803a934da9c05b5953a91ebf006696ffc72b8fdc783fb0385e2"
    )
    assert provenance["captured_at_utc"] == "2026-11-05T04:53:11.824138+00:00"
    assert provenance["original_record_count"] == 1000
    assert provenance["selected_record_count"] == len(sample["rows"]) == 100
    assert provenance["selected_fare_cents"] == 232603
    assert sample["rows"][0] == {
        "id": "5df927370e71a46b13764268707c0a3342fa7d449acb4bf48781e6b60cc98778",
        "amount_cents": 1298,
        "currency": "USD",
    }
    assert provenance["selected_original_records"][0]["row_id"] == "row-q6jg~33gy~992a"
    report = client.post(
        "/workbench/api/rehearsal",
        json={
            "config": {"name": "fare-inspection", "schedule": "0 * * * *"},
            "partition": "2026-11-09",
            "rows": sample["rows"],
            "retained_sample_id": sample["sample_id"],
        },
    )
    assert report.status_code == 200
    evidence = report.json()["evidence"]
    assert evidence["sample_source"] == provenance
    assert evidence["summary"]["output_rows"] == 100
    assert evidence["currency_totals"] == [{"currency": "USD", "rows": 100, "amount_cents": 232603}]
    assert all(row["partition_date"] == "2026-11-09" for row in evidence["normalized_rows"])


def test_edited_retained_records_cannot_claim_original_source(client):
    sample = client.get("/workbench/api/rehearsal/sample").json()
    sample["rows"][0]["amount_cents"] += 1
    response = client.post(
        "/workbench/api/rehearsal",
        json={
            "config": {"name": "edited-fares", "schedule": "0 * * * *"},
            "partition": "2026-11-09",
            "rows": sample["rows"],
            "retained_sample_id": sample["sample_id"],
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize("filename", ["nyc-fares.json", "nyc-fares-metadata.json"])
def test_tampered_retained_bytes_fail_closed_without_reflecting_contents(
    client, monkeypatch, filename
):
    original = Path.read_bytes

    def corrupted(path):
        return b"SECRET-MARKER" if path.name == filename else original(path)

    monkeypatch.setattr(Path, "read_bytes", corrupted)
    response = client.get("/workbench/api/rehearsal/sample")
    assert response.status_code == 503
    assert "SECRET-MARKER" not in response.text


def test_bundled_original_source_bytes_have_pinned_dated_hashes():
    root = Path(__file__).parents[1]
    package = root / "src" / "pipefoundry" / "samples"
    raw = (package / "nyc-fares.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "942e7b07bf180803a934da9c05b5953a91ebf006696ffc72b8fdc783fb0385e2"
    )
    assert hashlib.sha256((package / "nyc-fares-metadata.json").read_bytes()).hexdigest() == (
        "9cdbd7ec9e538c352e18aa1a4712abc04974a6030c9cf3e46e56496d3fd9c678"
    )
