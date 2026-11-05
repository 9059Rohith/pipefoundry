"""Real public GitHub evidence with shared refresh ownership and provider cooldowns."""

import hashlib
import json
import logging
import math
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
from fastapi import HTTPException

from pipefoundry.github_store import GitHubStore

FRESH_SECONDS = 600
MAX_STALE_SECONDS = 86400
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CAPACITY = 8
REFILL_SECONDS = 90
LEASE_SECONDS = 30
LOGGER = logging.getLogger(__name__)


def content_digest(data):
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def observed_time(evidence):
    try:
        value = datetime.fromisoformat(evidence["observed_at"])
        return value.timestamp() if value.tzinfo is not None else None
    except (ValueError, KeyError, TypeError, OverflowError):
        return None


def read_cached_evidence(request_key):
    if request_key != "9059rohith/pipefoundry" and not request_key.startswith(
        "9059rohith/pipefoundry/"
    ):
        return None
    try:
        captured = json.loads(
            Path(__file__).with_name("github_repository_cache.json").read_text(encoding="utf-8")
        )
        if captured["data"]["private"] is not False:
            return None
        related = captured.get("related", {})
        if not isinstance(related, dict):
            return None
        evidence = (
            {key: value for key, value in captured.items() if key != "related"}
            if request_key == "9059rohith/pipefoundry"
            else related.get(request_key)
        )
        if (
            not evidence
            or evidence["source"].lower() != "https://api.github.com/repos/" + request_key
        ):
            return None
        digest = content_digest(evidence["data"])
        if "content_sha256" in evidence and evidence["content_sha256"] != digest:
            return None
        if request_key != "9059rohith/pipefoundry" and "content_sha256" not in evidence:
            return None
        return {**evidence, "content_sha256": digest}
    except (OSError, ValueError, KeyError, TypeError):
        return None


class GitHubCache:
    def __init__(self, store=None, *, clock=time.time):
        self.store = store or GitHubStore.configured()
        self.clock = clock

    def _result(self, evidence, checked, status, retry=0):
        stale = self.clock() - checked >= FRESH_SECONDS
        backend = "postgresql" if self.store.dsn else "sqlite"
        if status == "stale-cache-unavailable":
            backend = "unavailable"
        result = {
            **evidence,
            "stale": stale,
            "cache_status": status,
            "validated_at": datetime.fromtimestamp(checked, UTC).isoformat(),
            "cache_seconds": FRESH_SECONDS,
            "cache_backend": backend,
        }
        if stale:
            result["warning"] = (
                "Using previously fetched public evidence at its original observation time. "
                "The next GitHub refresh waits for its shared request budget or provider reset."
            )
        if retry:
            result["retry_after_seconds"] = retry
        return result

    def _fallback(self, evidence, checked, status, retry, code=429):
        if evidence and checked is not None and 0 <= self.clock() - checked <= MAX_STALE_SECONDS:
            return self._result(evidence, checked, status, retry)
        raise HTTPException(
            code,
            "GitHub is temporarily unavailable and no usable cached evidence exists.",
            headers={"Retry-After": str(max(1, retry))},
        )

    def _claim(self, repo, key, seed, owner):
        now = self.clock()
        with self.store.connection() as db:
            db.execute(
                "INSERT INTO pf_github_refresh(id,tokens,updated_at) VALUES(1,?,?) "
                "ON CONFLICT(id) DO NOTHING",
                (CAPACITY, now),
            )
            row = db.execute(
                "SELECT payload,checked_at,revoked_until FROM pf_github_cache WHERE request_key=?",
                (key,),
            ).fetchone()
            if row is None:
                checked = observed_time(seed) if seed else None
                valid_seed = checked is not None and 0 <= now - checked <= MAX_STALE_SECONDS
                db.execute(
                    "INSERT INTO pf_github_cache(request_key,repository,payload,checked_at) "
                    "VALUES(?,?,?,?)",
                    (
                        key,
                        repo.lower(),
                        json.dumps(seed) if valid_seed else None,
                        checked if valid_seed else 0,
                    ),
                )
                row = (json.dumps(seed) if valid_seed else None, checked if valid_seed else 0, 0)
            evidence = json.loads(row[0]) if row[0] else None
            checked = row[1]
            # Bound keys even when a request is stopped by a provider cooldown.
            db.execute(
                "DELETE FROM pf_github_cache WHERE request_key IN "
                "(SELECT request_key FROM pf_github_cache WHERE request_key<>? "
                "ORDER BY revoked_until DESC,checked_at DESC LIMIT 128 OFFSET 127)",
                (key,),
            )
            if row[2] > now:
                raise HTTPException(404, "Repository or resource is not publicly accessible")
            if evidence and 0 <= now - checked < FRESH_SECONDS:
                return "cached", evidence, checked, 0
            state = db.execute(
                "SELECT owner,lease_until,cooldown_until,tokens,updated_at "
                "FROM pf_github_refresh WHERE id=1"
            ).fetchone()
            if state[2] > now:
                return "cooldown", evidence, checked, math.ceil(state[2] - now)
            if state[1] > now:
                return "busy", evidence, checked, 1
            tokens = min(CAPACITY, state[3] + max(0, now - state[4]) / REFILL_SECONDS)
            if tokens < 1:
                return "budget", evidence, checked, math.ceil((1 - tokens) * REFILL_SECONDS)
            db.execute(
                "UPDATE pf_github_refresh SET owner=?,lease_until=?,tokens=?,updated_at=? "
                "WHERE id=1",
                (owner, now + LEASE_SECONDS, tokens - 1, now),
            )
            return "fetch", evidence, checked, 0

    def _finish(self, owner, key, evidence=None, *, cooldown=0, revoked=False):
        now = self.clock()
        with self.store.connection() as db:
            state = db.execute(
                "SELECT owner,cooldown_until FROM pf_github_refresh WHERE id=1"
            ).fetchone()
            if not state:
                return
            until = max(state[1], now + cooldown if cooldown else 0)
            if state[0] != owner:
                db.execute("UPDATE pf_github_refresh SET cooldown_until=? WHERE id=1", (until,))
                return
            if evidence is not None or revoked:
                db.execute(
                    "UPDATE pf_github_cache SET payload=?,checked_at=?,revoked_until=? "
                    "WHERE request_key=?",
                    (
                        json.dumps(evidence) if evidence else None,
                        now,
                        now + FRESH_SECONDS if revoked else 0,
                        key,
                    ),
                )
            db.execute(
                "UPDATE pf_github_refresh SET owner='',lease_until=0,cooldown_until=? WHERE id=1",
                (until,),
            )

    def inspect(self, repo, suffix, loader):
        key = repo.lower() + suffix
        source = f"https://api.github.com/repos/{repo}{suffix}"
        seed = loader(key)
        owner = uuid.uuid4().hex
        waiting_until = time.monotonic() + 20
        try:
            while True:
                action, cached, checked, retry = self._claim(repo, key, seed, owner)
                if action == "cached":
                    return self._result(cached, checked, "fresh-cache")
                if action == "fetch":
                    break
                if action != "busy" or cached or time.monotonic() >= waiting_until:
                    return self._fallback(cached, checked, "stale-" + action, retry)
                time.sleep(0.1)
            headers = {"Accept": "application/vnd.github+json", "User-Agent": "PipeFoundry"}
            if cached and isinstance(cached.get("etag"), str):
                etag = cached["etag"]
                if len(etag) <= 512 and "\r" not in etag and "\n" not in etag:
                    headers["If-None-Match"] = etag
            try:
                with httpx.Client(timeout=12, follow_redirects=False) as client:
                    response = client.get(source, headers=headers)
                if response.status_code == 404:
                    self._finish(owner, key, revoked=True)
                    raise HTTPException(404, "Repository or resource is not publicly accessible")
                if response.status_code in {403, 429}:
                    delays = [60]
                    if response.headers.get("retry-after", "").isdecimal():
                        delays.append(int(response.headers["retry-after"]))
                    if response.headers.get("x-ratelimit-reset", "").isdecimal():
                        delays.append(
                            int(response.headers["x-ratelimit-reset"]) - int(self.clock())
                        )
                    retry = max(delays)
                    self._finish(owner, key, cooldown=retry)
                    return self._fallback(cached, checked, "stale-rate-limit", retry)
                if response.status_code == 304 and cached:
                    evidence = {**cached, "etag": response.headers.get("etag", cached.get("etag"))}
                elif response.status_code == 200 and len(response.content) <= MAX_RESPONSE_BYTES:
                    data = response.json()
                    if not isinstance(data, (dict, list)):
                        raise ValueError("Unexpected public GitHub response shape")
                    if isinstance(data, dict) and data.get("private") is True:
                        self._finish(owner, key, revoked=True)
                        raise HTTPException(
                            404, "Repository or resource is not publicly accessible"
                        )
                    evidence = {
                        "data": data,
                        "source": source,
                        "observed_at": datetime.fromtimestamp(self.clock(), UTC).isoformat(),
                        "cache_seconds": FRESH_SECONDS,
                        "etag": response.headers.get("etag"),
                        "content_sha256": content_digest(data),
                    }
                else:
                    raise ValueError("Public GitHub inspection unavailable")
                cooldown = 0
                if response.headers.get("x-ratelimit-remaining") == "0":
                    reset = response.headers.get("x-ratelimit-reset", "")
                    cooldown = max(60, int(reset) - int(self.clock())) if reset.isdecimal() else 60
                self._finish(owner, key, evidence, cooldown=cooldown)
                return self._result(
                    evidence, self.clock(), "revalidated" if response.status_code == 304 else "live"
                )
            except (httpx.HTTPError, ValueError):
                self._finish(owner, key, cooldown=60)
                return self._fallback(cached, checked, "stale-upstream-error", 60, code=502)
        except (psycopg.Error, sqlite3.Error, OSError) as error:
            LOGGER.warning("GitHub shared cache unavailable type=%s", type(error).__name__)
            return self._fallback(
                seed, observed_time(seed) if seed else None, "stale-cache-unavailable", 60, code=503
            )
