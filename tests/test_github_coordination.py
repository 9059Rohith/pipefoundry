"""Provider failures and concurrent page loads must not multiply GitHub requests."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import HTTPException

from pipefoundry import workbench
from pipefoundry.github_cache import FRESH_SECONDS, GitHubCache, read_cached_evidence
from pipefoundry.github_store import GitHubStore

REPO = "9059Rohith/pipefoundry"


def evidence():
    captured = read_cached_evidence(REPO.lower())
    assert captured is not None
    return captured


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    workbench._cache.clear()
    monkeypatch.delenv("PIPEFOUNDRY_METADATA_DSN", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(workbench, "read_cached_evidence", lambda key: None)
    yield
    workbench._cache.clear()


def test_provider_reset_blocks_other_views_without_more_upstream_calls(monkeypatch):
    calls = []

    def get(_client, url, **_kwargs):
        calls.append(url)
        return httpx.Response(429, headers={"Retry-After": "120"})

    monkeypatch.setattr(httpx.Client, "get", get)
    for view in ("repository", "workflows", "runs"):
        with pytest.raises(HTTPException) as error:
            workbench.github("owner/project", view)
        assert error.value.status_code == 429
    assert len(calls) == 1


def test_separate_instances_reuse_persisted_real_response(tmp_path, monkeypatch):
    captured = evidence()
    calls = []

    def get(_client, url, **_kwargs):
        calls.append(url)
        return httpx.Response(200, json=captured["data"], headers={"ETag": captured["etag"]})

    monkeypatch.setattr(httpx.Client, "get", get)
    path = str(tmp_path / "shared.db")
    first = GitHubCache(GitHubStore(sqlite_path=path))
    second = GitHubCache(GitHubStore(sqlite_path=path))
    one = first.inspect(REPO, "", lambda key: None)
    two = second.inspect(REPO, "", lambda key: None)
    assert one["data"] == two["data"] == captured["data"]
    assert len(calls) == 1 and two["cache_status"] == "fresh-cache"


def test_all_captured_views_remain_available_during_shared_cooldown(monkeypatch):
    import json
    from datetime import datetime
    from pathlib import Path

    captured = evidence()
    now = datetime.fromisoformat(captured["observed_at"]).timestamp() + FRESH_SECONDS + 120
    bundle = json.loads(
        Path(workbench.__file__).with_name("github_repository_cache.json").read_text("utf-8")
    )
    calls = []

    def get(_client, url, **_kwargs):
        calls.append(url)
        return httpx.Response(429, headers={"Retry-After": "120"})

    monkeypatch.setattr(httpx.Client, "get", get)
    cache = GitHubCache(clock=lambda: now)
    first = cache.inspect(REPO, "", read_cached_evidence)
    assert first["stale"] and first["observed_at"] == captured["observed_at"]
    for key, original in bundle["related"].items():
        result = cache.inspect(REPO, key[len(REPO) :], read_cached_evidence)
        assert result["content_sha256"] == original["content_sha256"]
        assert result["data"] == original["data"]
    assert len(calls) == 1


def test_conditional_validation_keeps_capture_time_and_exact_data(monkeypatch):
    from datetime import datetime

    captured = evidence()
    now = [datetime.fromisoformat(captured["observed_at"]).timestamp()]
    cache = GitHubCache(clock=lambda: now[0])
    calls = []

    def get(_client, _url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return httpx.Response(200, json=captured["data"], headers={"ETag": captured["etag"]})
        return httpx.Response(304)

    monkeypatch.setattr(httpx.Client, "get", get)
    first = cache.inspect(REPO, "", lambda key: None)
    now[0] += FRESH_SECONDS + 1
    second = cache.inspect(REPO, "", lambda key: None)
    assert calls[1]["headers"]["If-None-Match"] == captured["etag"]
    assert second["observed_at"] == first["observed_at"]
    assert second["validated_at"] != first["validated_at"]
    assert second["data"] == first["data"] and not second["stale"]


def test_authoritative_not_found_discards_capture_instead_of_serving_it(monkeypatch):
    from datetime import datetime

    captured = evidence()
    now = datetime.fromisoformat(captured["observed_at"]).timestamp() + FRESH_SECONDS + 1
    cache = GitHubCache(clock=lambda: now)
    calls = []

    def get(*_args, **_kwargs):
        calls.append(1)
        return httpx.Response(404)

    monkeypatch.setattr(httpx.Client, "get", get)
    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            cache.inspect(REPO, "", read_cached_evidence)
        assert error.value.status_code == 404
    assert len(calls) == 1


def test_shared_reset_uses_longer_provider_deadline_and_keeps_key_count_bounded(monkeypatch):
    now = 1_800_000_000
    cache = GitHubCache(clock=lambda: now)
    calls = []

    def get(*_args, **_kwargs):
        calls.append(1)
        return httpx.Response(
            429, headers={"Retry-After": "120", "X-RateLimit-Reset": str(now + 240)}
        )

    monkeypatch.setattr(httpx.Client, "get", get)
    for index in range(150):
        with pytest.raises(HTTPException) as error:
            cache.inspect(f"owner/repo-{index}", "", lambda key: None)
        assert error.value.status_code == 429
        assert error.value.headers["Retry-After"] == "240"
    assert len(calls) == 1
    with cache.store.connection() as database:
        assert database.execute("SELECT count(*) FROM pf_github_cache").fetchone()[0] <= 128


def test_expired_capture_is_not_presented_as_a_success(monkeypatch):
    from datetime import datetime

    captured = evidence()
    now = datetime.fromisoformat(captured["observed_at"]).timestamp() + 86401
    cache = GitHubCache(clock=lambda: now)
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **kw: httpx.Response(503))
    with pytest.raises(HTTPException) as error:
        cache.inspect(REPO, "", read_cached_evidence)
    assert error.value.status_code == 502


def test_legacy_capture_remains_usable_and_bad_recorded_hash_is_rejected(tmp_path, monkeypatch):
    import json

    from pipefoundry import github_cache

    captured = evidence()
    captured.pop("content_sha256")
    path = tmp_path / "github_repository_cache.json"
    path.write_text(json.dumps(captured), encoding="utf-8")
    monkeypatch.setattr(github_cache, "__file__", str(tmp_path / "github_cache.py"))
    assert read_cached_evidence(REPO.lower())["data"] == captured["data"]
    captured["content_sha256"] = "0" * 64
    path.write_text(json.dumps(captured), encoding="utf-8")
    assert read_cached_evidence(REPO.lower()) is None


def test_concurrent_identical_reads_fetch_once(monkeypatch):
    calls = []
    gate = threading.Barrier(4)

    def get(_client, url, **_kwargs):
        calls.append(url)
        time.sleep(0.15)
        return httpx.Response(200, json={"full_name": "owner/project", "private": False})

    def inspect(_index):
        gate.wait(timeout=5)
        return workbench.github("owner/project", "repository")

    monkeypatch.setattr(httpx.Client, "get", get)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(inspect, range(4)))
    assert all(value["data"]["full_name"] == "owner/project" for value in results)
    assert len(calls) == 1


def test_first_recruiter_session_can_open_five_feeds_and_three_run_details(monkeypatch):
    import json
    from pathlib import Path

    bundle = json.loads(
        Path("src/pipefoundry/github_repository_cache.json").read_text(encoding="utf-8")
    )
    related = bundle["related"]
    keys = [REPO.lower()] + [key for key in related if "/jobs?" not in key]
    keys += [key for key in related if "/jobs?" in key][:3]
    assert len(keys) == 8
    captures = {REPO.lower(): bundle, **related}
    calls = []

    def get(_client, url, **_kwargs):
        key = str(url).removeprefix("https://api.github.com/repos/").lower()
        calls.append(key)
        return httpx.Response(200, json=captures[key]["data"])

    monkeypatch.setattr(httpx.Client, "get", get)
    cache = GitHubCache(clock=lambda: 1_800_000_000)
    for key in keys:
        result = cache.inspect(REPO, key[len(REPO) :], lambda key: None)
        assert result["data"] == captures[key]["data"]
    assert len(calls) == 8
