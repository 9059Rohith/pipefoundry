import json
import subprocess
import sys


def test_benchmark_measures_each_stage_and_persists_samples(tmp_path):
    target = tmp_path / "benchmark.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark.py",
            "--samples",
            "5",
            "--execution-samples",
            "3",
            "--output",
            str(target),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    measurements = json.loads(target.read_text())["measurements"]
    assert set(measurements) == {"validate", "template", "render", "local_execution"}
    for metric in measurements.values():
        assert len(metric["samples_ms"]) >= 3
        assert 0 < metric["p50_ms"] <= metric["p95_ms"] <= metric["p99_ms"]
