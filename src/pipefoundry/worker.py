"""Fixed workload entrypoint. No uploaded code and no shell execution."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pipefoundry.models import Pipeline, relative_path
from pipefoundry.workloads import FIXTURE, fetch_orders, ingest, ingest_postgres


def data_path(root: Path, relative: str) -> Path:
    relative_path(relative)
    root = root.resolve()
    base = (root / "data").resolve()
    target = (base / relative).resolve()
    if not base.is_relative_to(root) or not target.is_relative_to(base) or target == base:
        raise ValueError("data path escapes the configured root")
    return target


def run(config: Pipeline, root: str | Path, partition: str | None = None) -> dict:
    root = Path(root).resolve()
    partition = partition or datetime.now(UTC).date().isoformat()
    if config.input.connector == "spark_json":
        from pipefoundry.spark_job import transform

        return transform(
            data_path(root, config.input.path), data_path(root, f"{config.output.path}/{partition}")
        )
    rows = FIXTURE if config.input.connector == "fixture" else fetch_orders()
    if config.output.connector == "postgres":
        return ingest_postgres(rows, partition)
    return ingest(rows, data_path(root, config.output.path), partition)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--partition")
    arguments = parser.parse_args()
    try:
        if arguments.config.stat().st_size > 32768:
            raise ValueError("config too large")
        config = Pipeline.model_validate_json(arguments.config.read_text(encoding="utf-8"))
        print(json.dumps(run(config, arguments.root, arguments.partition)))
        return 0
    except Exception as exc:
        # DSNs, URLs and driver traces may contain credentials; do not log them.
        print(
            json.dumps({"error": type(exc).__name__, "message": "workload failed"}), file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
