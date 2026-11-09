"""A bounded projection of the original pinned NYC Open Data fare capture."""

import hashlib
import json
from fractions import Fraction
from pathlib import Path

from fastapi import HTTPException

from pipefoundry.manifest_review import fingerprint

SAMPLE_ID = "nyc-taxi-fares-v1"
SOURCE_SHA256 = "942e7b07bf180803a934da9c05b5953a91ebf006696ffc72b8fdc783fb0385e2"
METADATA_SHA256 = "9cdbd7ec9e538c352e18aa1a4712abc04974a6030c9cf3e46e56496d3fd9c678"
SAMPLES = Path(__file__).with_name("samples")


def retained_sample():
    try:
        raw_path, metadata_path = SAMPLES / "nyc-fares.json", SAMPLES / "nyc-fares-metadata.json"
        if raw_path.stat().st_size > 110000 or metadata_path.stat().st_size > 4096:
            raise ValueError("retained bytes exceed bounds")
        raw, metadata_raw = raw_path.read_bytes(), metadata_path.read_bytes()
        if (
            hashlib.sha256(raw).hexdigest() != SOURCE_SHA256
            or hashlib.sha256(metadata_raw).hexdigest() != METADATA_SHA256
        ):
            raise ValueError("retained source integrity mismatch")
        original, metadata = json.loads(raw), json.loads(metadata_raw)
        if len(original) != metadata["rows"] or metadata["sha256"] != SOURCE_SHA256:
            raise ValueError("retained metadata mismatch")
        cents = [Fraction(row["fare_amount"]) * 100 for row in original]
        if any(value.denominator != 1 for value in cents):
            raise ValueError("fare requires fractional cents")
        if sum(cents) != metadata["total_fare_cents"]:
            raise ValueError("retained total mismatch")
        selected = original[:100]
        rows = [
            {
                "id": hashlib.sha256(row["row_id"].encode()).hexdigest(),
                "amount_cents": value.numerator,
                "currency": "USD",
            }
            for row, value in zip(selected, cents[:100], strict=True)
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, "Retained fare sample is unavailable") from exc
    return {
        "sample_id": SAMPLE_ID,
        "rows": rows,
        "provenance": {
            "source_url": metadata["source_url"],
            "captured_at_utc": metadata["captured_at_utc"],
            "source_sha256": SOURCE_SHA256,
            "metadata_sha256": METADATA_SHA256,
            "original_record_count": len(original),
            "selected_record_count": len(selected),
            "selection": "First 100 records in the original captured response order",
            "mapping": (
                "id = SHA-256 of original UTF-8 row_id; amount_cents = exact fare_amount × 100; "
                "currency = USD. These are mapped NYC taxi fare observations, not customer orders."
            ),
            "partition_note": (
                "The selected partition is an explicit output storage date. "
                "It does not replace or convert the original pickup timestamps."
            ),
            "selected_fare_cents": sum(value.numerator for value in cents[:100]),
            "mapped_rows_sha256": fingerprint(rows),
            "selected_original_records": selected,
        },
    }
