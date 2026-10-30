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
    report = json.loads(target.read_text())
    measurements = report["measurements"]
    assert report["artifact_counts"]["authored_lines"] == 11
    assert report["artifact_counts"]["generated_files"] == 8
    assert report["artifact_counts"]["generated_lines"] > 100
    assert set(measurements) == {"validate", "template", "render", "preview", "local_execution"}
    for metric in measurements.values():
        assert len(metric["samples_ms"]) >= 3
        assert 0 < metric["p50_ms"] <= metric["p95_ms"] <= metric["p99_ms"]
