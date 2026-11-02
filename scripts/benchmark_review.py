"""Bounded static review benchmark; no AI, cluster, database or worker execution."""

import argparse
import json
import platform
from pathlib import Path

from benchmark import measure

from pipefoundry.manifest_review import ReviewRequest, review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    if not 3 <= args.samples <= 100:
        parser.error("samples must be 3..100")
    body = ReviewRequest.model_validate(
        {
            "config": {
                "name": "review-benchmark",
                "schedule": "*/5 * * * *",
                "resources": {"cpu_millis": 4000, "memory_mib": 8192},
            },
            "baseline": {"name": "review-benchmark", "schedule": "0 * * * *"},
        }
    )
    result = review(body)
    measurement = measure(lambda _: review(body), args.samples)
    output = {
        "operation": "two strict configs -> server manifests -> policy audit -> diff -> SHA-256",
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "input_bytes": len(body.model_dump_json().encode()),
        "output_bytes": len(json.dumps(result).encode()),
        "measurement": measurement,
        "scope": "Local pure function; no network, AI, workers or cluster. Not hosted latency.",
    }
    Path("evidence/manifest-review-benchmark.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in measurement.items() if k != "samples_ms"}))


if __name__ == "__main__":
    main()
