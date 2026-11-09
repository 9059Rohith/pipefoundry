"""Bounded in-memory samples using the SQL worker's real transform. No I/O."""

from collections import defaultdict
from datetime import date

import yaml
from pydantic import Field, ValidationError, field_validator, model_validator

from pipefoundry.manifest_review import canonical, fingerprint
from pipefoundry.models import Pipeline, StrictModel
from pipefoundry.render import objects
from pipefoundry.workloads import Order, normalize_orders


class RehearsalRequest(StrictModel):
    config: Pipeline
    partition: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    rows: list[dict] = Field(min_length=1, max_length=100)

    @field_validator("partition")
    @classmethod
    def valid_partition(cls, value):
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def sql_transform_only(self):
        if self.config.input.connector == "spark_json":
            raise ValueError("sample rehearsal supports the SQL order transform only")
        return self


FIELD_RULES = {
    "id": "Use 1–80 ASCII letters, digits, underscores or hyphens.",
    "amount_cents": "Use an integer from 0 to 1000000000; booleans are rejected.",
    "currency": "Use exactly three ASCII letters; the transform converts them to uppercase.",
    "unknown field": "Only id, amount_cents and currency are permitted.",
}


def rehearse(body: RehearsalRequest):
    issues, invalid_rows = [], 0
    for index, row in enumerate(body.rows, 1):
        try:
            Order.model_validate(row)
        except ValidationError as exc:
            invalid_rows += 1
            for error in exc.errors(include_input=False, include_context=False):
                key = error["loc"][0]
                field = key if key in FIELD_RULES and key != "unknown field" else "unknown field"
                issues.append({"row": index, "field": field, "rule": FIELD_RULES[field]})

    # Whole-batch validation matches normalize_orders: no partial accepted result.
    normalized = [] if issues else normalize_orders(body.rows)
    lineage, totals = defaultdict(list), {}
    if not issues:
        for index, row in enumerate(body.rows, 1):
            lineage[row["id"]].append(index)
        for row in normalized:
            group = totals.setdefault(
                row["currency"], {"currency": row["currency"], "rows": 0, "amount_cents": 0}
            )
            group["rows"] += 1
            group["amount_cents"] += row["amount_cents"]
    config = body.config.model_dump()
    evidence = {
        "version": "sample-rehearsal-v1",
        "accepted": not issues,
        "scope": (
            "Submitted sample only; the configured connector was not read. "
            "No database writes, workload execution or deployment. "
            "Sample rows are not embedded in the generated configuration or manifest."
        ),
        "partition": body.partition,
        "config": config,
        "config_json": canonical(config),
        "config_sha256": fingerprint(config),
        "sample_sha256": fingerprint(body.rows),
        "summary": {
            "input_rows": len(body.rows),
            "output_rows": len(normalized),
            "replaced_rows": len(body.rows) - len(normalized) if not issues else 0,
            "currency_normalizations": sum(
                row["currency"] != row["currency"].upper() for row in body.rows
            )
            if not issues
            else 0,
        },
        "invalid_rows": invalid_rows,
        "issues": issues[:100],
        "issues_truncated": len(issues) > 100,
        "duplicates": [
            {"id": key, "source_rows": indexes, "winner_row": indexes[-1]}
            for key, indexes in lineage.items()
            if len(indexes) > 1
        ],
        "currency_totals": [totals[key] for key in sorted(totals)],
        "normalized_rows": [{"partition_date": body.partition, **row} for row in normalized],
        "manifest": yaml.safe_dump_all(objects(body.config, 1), sort_keys=False),
    }
    return {"evidence": evidence, "evidence_sha256": fingerprint(evidence)}
