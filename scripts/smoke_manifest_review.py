"""Public production review smoke test. Never invokes AI or deployment execution."""

import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://pipefoundry.vercel.app")
    args = parser.parse_args()
    checks = []
    with httpx.Client(base_url=args.url, timeout=40, follow_redirects=False) as client:

        def call(method, route, expected=200, **kwargs):
            started = time.perf_counter()
            response = client.request(method, route, **kwargs)
            assert response.status_code == expected, (route, response.status_code)
            checks.append(
                {
                    "route": route,
                    "method": method,
                    "status": response.status_code,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            return response

        page = call("GET", "/workbench/review")
        assert 'data-page="review"' in page.text
        assert "unsafe-inline" not in page.headers["content-security-policy"]
        assert 'data-nav="review"' in page.text
        script = call("GET", "/workbench/assets/app.js")
        assert "review-export" in script.text and "function review()" in script.text
        baseline = {"name": "public-review-smoke", "schedule": "0 * * * *"}
        candidate = {**baseline, "resources": {"cpu_millis": 1000, "memory_mib": 512}}
        response = call(
            "POST",
            "/workbench/api/review",
            json={
                "config": candidate,
                "baseline": baseline,
            },
        )
        result = response.json()
        evidence = result["evidence"]
        encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(encoded.encode()).hexdigest() == result["evidence_sha256"]
        assert evidence["comparison"]["escalations"] == 2
        assert evidence["current"]["summary"]["fail"] == 0
        assert evidence["cluster_validation"] == "not performed"
        rejected = call(
            "POST",
            "/workbench/api/review",
            expected=422,
            json={
                "config": {**candidate, "secret": "NEVER-REFLECT"},
            },
        )
        assert "NEVER-REFLECT" not in rejected.text
        call("POST", "/workbench/api/review", expected=413, content=b"x" * 32769)
        call("POST", "/releases/apply", expected=401, json={})
        call("POST", "/workbench/api/agent", expected=401, json={})
    output = {
        "url": args.url,
        "checks": checks,
        "summary": evidence["current"]["summary"],
        "evidence_sha256": result["evidence_sha256"],
        "risk_escalations": 2,
        "model_requests": 0,
        "cluster_actions": 0,
    }
    Path("evidence/manifest-review-production.json").write_text(
        json.dumps(output, indent=2), encoding="utf-8"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
