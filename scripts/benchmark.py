"""Reproducible real measurements, including worker process startup and disk IO."""

import argparse
import json
import math
import platform
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from pipefoundry.cli import load
from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline
from pipefoundry.render import objects, render


def measure(operation, count):
    samples = []
    for index in range(count):
        started = time.perf_counter_ns()
        operation(index)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(samples)
    return {
        "count": count,
        "samples_ms": samples,
        **{
            f"p{percent}_ms": ordered[math.ceil(percent / 100 * count) - 1]
            for percent in (50, 95, 99)
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--execution-samples", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("evidence/benchmark.json"))
    args = parser.parse_args()
    if not 3 <= args.samples <= 1000 or not 3 <= args.execution_samples <= 100:
        parser.error("samples must be 3..1000, execution samples 3..100")
    config = load(str(Path(__file__).resolve().parents[1] / "examples/orders-local.yaml"))
    raw = config.model_dump()
    with tempfile.TemporaryDirectory(prefix="pipefoundry-benchmark-") as temporary:
        root = Path(temporary)
        engine = Platform(root / "state")
        # Explicit warmup excludes first import/cache startup; process startup still counted.
        for _ in range(3):
            Pipeline.model_validate(raw)
            objects(config, 1)
        results = {
            "validate": measure(lambda _: Pipeline.model_validate(raw), args.samples),
            "template": measure(lambda _: objects(config, 1), args.samples),
            "render": measure(
                lambda index: render(config, index + 1, root / str(index)), args.samples
            ),
            "local_execution": measure(lambda _: engine.deploy(config), args.execution_samples),
        }
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "environment": {"os": platform.platform(), "python": platform.python_version()},
        "method": "nearest-rank percentiles; sequential wall time; fixture 3 orders; local disk",
        "caveat": "Local timings only. No claim about EKS, network throughput or production SLA.",
        "measurements": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: {field: value for field, value in metric.items() if field != "samples_ms"}
                for key, metric in results.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
