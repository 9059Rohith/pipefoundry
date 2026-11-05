"""Verify every source-backed GitHub view through the public application."""

import concurrent.futures
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = json.loads(
    (ROOT / "src/pipefoundry/github_repository_cache.json").read_text(encoding="utf-8")
)
ENTRIES = {"9059rohith/pipefoundry": BUNDLE, **BUNDLE["related"]}
BASE = "https://rohith-pipefoundry.vercel.app"


def check(key):
    suffix = key.removeprefix("9059rohith/pipefoundry")
    view = (
        "repository"
        if not suffix
        else "run"
        if "/jobs?" in suffix
        else "runs"
        if "/runs?" in suffix
        else "workflows"
        if "/workflows?" in suffix
        else "releases"
        if "/releases?" in suffix
        else "commits"
    )
    query = {"repo": "9059Rohith/pipefoundry", "view": view}
    if view == "run":
        query["run_id"] = suffix.split("/")[3]
    url = BASE + "/workbench/api/github?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url, timeout=45) as response:
        value = json.load(response)
        assert response.code == 200
    assert value["cache_backend"] == "postgresql"
    assert value["source"].lower() == "https://api.github.com/repos/" + key
    encoded = json.dumps(
        value["data"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert hashlib.sha256(encoded).hexdigest() == value["content_sha256"]
    assert datetime.fromisoformat(value["observed_at"]).tzinfo is not None
    assert datetime.fromisoformat(value["validated_at"]).tzinfo is not None
    if value["observed_at"] == ENTRIES[key]["observed_at"]:
        assert value["data"] == ENTRIES[key]["data"]
    return {
        "view": view,
        "request_key": key,
        "status": 200,
        "cache_status": value["cache_status"],
        "observed_at": value["observed_at"],
        "validated_at": value["validated_at"],
        "source": value["source"],
        "content_sha256": value["content_sha256"],
        "cache_backend": value["cache_backend"],
        "stale": value["stale"],
    }


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        checks = list(pool.map(check, ENTRIES))
    destination = ROOT / "evidence/github-public.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(
        json.dumps(
            {
                "checked_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "checks": checks,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "passed": True,
                "views": len(checks),
                "http_200": len(checks),
                "postgresql": len(checks),
                "stale_captures": sum(row["stale"] for row in checks),
            }
        )
    )
