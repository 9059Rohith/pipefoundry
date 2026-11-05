"""Capture only official anonymous public PipeFoundry GitHub evidence, serially."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPO = "9059Rohith/pipefoundry"
ORIGIN = f"https://api.github.com/repos/{REPO}"
MAX_BYTES = 4 * 1024 * 1024
SUFFIXES = (
    "",
    "/actions/workflows?per_page=50",
    "/actions/runs?per_page=30",
    "/releases?per_page=30",
    "/commits?per_page=30",
)


def content_sha256(data):
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify(bundle):
    entries = {REPO.lower(): {k: v for k, v in bundle.items() if k != "related"}}
    entries.update(bundle.get("related", {}))
    for key, evidence in entries.items():
        suffix = key.removeprefix(REPO.lower())
        known_suffix = suffix in SUFFIXES or re.fullmatch(
            r"/actions/runs/[1-9][0-9]{0,14}/jobs\?per_page=50", suffix
        )
        if (
            not key.startswith(REPO.lower())
            or not known_suffix
            or evidence["source"] != ORIGIN + suffix
        ):
            raise ValueError(f"Unexpected evidence source: {key}")
        if evidence["content_sha256"] != content_sha256(evidence["data"]):
            raise ValueError(f"Evidence digest mismatch: {key}")
        if evidence["cache_seconds"] != 600:
            raise ValueError(f"Unexpected fresh cache duration: {key}")
        observed = datetime.fromisoformat(evidence["observed_at"])
        if observed.utcoffset() is None or observed > datetime.now(UTC):
            raise ValueError(f"Invalid observation time: {key}")
    return len(entries)


def capture(output, report_path, max_jobs):
    report = {"started_at": datetime.now(UTC).isoformat(), "requests": []}
    entries = {}
    stopped = False

    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:

        def fetch(suffix):
            nonlocal stopped
            if stopped:
                return
            source = ORIGIN + suffix
            record = {"source": source}
            try:
                response = client.get(
                    source,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "PipeFoundry-evidence-capture",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                observed = datetime.now(UTC).isoformat()
                record.update(
                    {
                        "status": response.status_code,
                        "observed_at": observed,
                        "rate_limit_remaining": response.headers.get("x-ratelimit-remaining"),
                        "rate_limit_reset": response.headers.get("x-ratelimit-reset"),
                        "retry_after": response.headers.get("retry-after"),
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    entries[REPO.lower() + suffix] = {
                        "data": data,
                        "source": source,
                        "observed_at": observed,
                        "cache_seconds": 600,
                        "etag": response.headers.get("etag"),
                        "content_sha256": content_sha256(data),
                    }
                else:
                    # Record actual errors separately, never as successful source evidence.
                    record["error"] = response.json().get("message", "GitHub request failed")
                if response.status_code in {403, 429}:
                    stopped = True
                    report["stopped_reason"] = "Provider rejected requests; no retry attempted."
                elif response.headers.get("x-ratelimit-remaining") == "0":
                    stopped = True
                    report["stopped_reason"] = "Provider remaining quota is zero; await reset."
            except (httpx.HTTPError, ValueError) as exc:
                record["error"] = type(exc).__name__
                stopped = True
                report["stopped_reason"] = "Transport or response error; no retry attempted."
            report["requests"].append(record)

        for suffix in SUFFIXES:
            fetch(suffix)
        runs = entries.get(REPO.lower() + "/actions/runs?per_page=30", {})
        for run in runs.get("data", {}).get("workflow_runs", [])[:max_jobs]:
            run_id = run.get("id")
            if isinstance(run_id, int) and 0 < run_id < 10**15:
                fetch(f"/actions/runs/{run_id}/jobs?per_page=50")

    if REPO.lower() in entries:
        bundle = entries.pop(REPO.lower())
        bundle["related"] = entries
        verify(bundle)
        payload = (json.dumps(bundle, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if len(payload) > MAX_BYTES:
            raise ValueError("Capture exceeds the 4 MiB bundle limit; output was not replaced")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
        report.update(
            {
                "evidence_count": len(entries) + 1,
                "bundle_bytes": len(payload),
                "bundle_sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    else:
        report["stopped_reason"] = report.get("stopped_reason", "Repository capture unavailable")
    report["finished_at"] = datetime.now(UTC).isoformat()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if "evidence_count" in report else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "src/pipefoundry/github_repository_cache.json"
    )
    parser.add_argument("--report", type=Path, default=ROOT / ".runtime/github-capture-report.json")
    parser.add_argument("--max-jobs", type=int, choices=range(31), default=30)
    parser.add_argument("--verify", action="store_true", help="Verify the bundle offline only")
    args = parser.parse_args()
    if args.verify:
        if args.output.stat().st_size > MAX_BYTES:
            raise ValueError("Capture exceeds the 4 MiB bundle limit")
        count = verify(json.loads(args.output.read_text(encoding="utf-8")))
        print(json.dumps({"verified_evidence_count": count}))
        return 0
    return capture(args.output, args.report, args.max_jobs)


if __name__ == "__main__":
    raise SystemExit(main())
