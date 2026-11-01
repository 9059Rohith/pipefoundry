"""A genuine captured public repository response for rate-limit fallback only."""

import json
from pathlib import Path


def read_cached_evidence(request_key):
    if request_key != "9059rohith/pipefoundry":
        return None
    try:
        captured = json.loads(
            Path(__file__).with_name("github_repository_cache.json").read_text(encoding="utf-8")
        )
        if (
            captured["source"] != "https://api.github.com/repos/9059Rohith/pipefoundry"
            or captured["data"]["private"] is not False
        ):
            return None
        return captured
    except (OSError, ValueError, KeyError, TypeError):
        return None
