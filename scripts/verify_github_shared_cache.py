"""Native PostgreSQL proof using recorded real GitHub evidence; no GitHub requests."""

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import psycopg
from psycopg.conninfo import make_conninfo

from pipefoundry.github_cache import FRESH_SECONDS, GitHubCache, read_cached_evidence
from pipefoundry.github_store import GitHubStore

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "9059Rohith/pipefoundry"
BUNDLE = ROOT / "src/pipefoundry/github_repository_cache.json"


def digest(data):
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@contextmanager
def isolated_postgres(bin_dir):
    """Same isolated-directory/random-port boundary as the archive replay helper."""
    scratch = ROOT / ".runtime"
    scratch.mkdir(exist_ok=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="github-cache-postgres-", dir=scratch) as folder:
        work = Path(folder).resolve()
        if work.parent != scratch.resolve():
            raise RuntimeError("Unexpected disposable cluster directory")
        data = work / "database"
        password = secrets.token_urlsafe(32)
        password_file = work / "password"
        password_file.write_text(password + "\n", encoding="utf-8")
        dsn = make_conninfo(
            host="127.0.0.1", port=port, dbname="postgres", user="postgres", password=password
        )

        def run(program, *args):
            executable = bin_dir / (program + ".exe" if os.name == "nt" else program)
            result = subprocess.run(
                [str(executable), *map(str, args)],
                capture_output=True,
                timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode:
                raise RuntimeError(f"Disposable PostgreSQL {program} failed ({result.returncode})")

        try:
            run(
                "initdb",
                "-D",
                data,
                "--username=postgres",
                "--auth=scram-sha-256",
                "--locale=C",
                "--encoding=UTF8",
                "--pwfile",
                password_file,
            )
        finally:
            password_file.unlink()

        process = None

        def start():
            nonlocal process
            executable = bin_dir / ("postgres.exe" if os.name == "nt" else "postgres")
            with (work / "postgres.log").open("ab") as log:
                process = subprocess.Popen(
                    [str(executable), "-D", str(data), "-h", "127.0.0.1", "-p", str(port)],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Disposable PostgreSQL exited during startup")
                try:
                    with psycopg.connect(dsn, connect_timeout=1):
                        return
                except psycopg.OperationalError:
                    time.sleep(0.1)
            raise RuntimeError("Disposable PostgreSQL readiness timed out")

        def stop():
            run("pg_ctl", "stop", "-D", data, "-m", "fast", "-w", "-t", "15")
            process.wait(timeout=5)

        try:
            start()
            yield dsn, lambda: (stop(), start())
        finally:
            if process is not None and process.poll() is None:
                try:
                    stop()
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)


def verify(dsn, restart):
    bundle = json.loads(BUNDLE.read_text(encoding="utf-8"))
    keys = [REPOSITORY.lower(), *bundle["related"]]
    entries = {key: read_cached_evidence(key) for key in keys}
    assert len(entries) == 31
    assert bundle["data"]["private"] is False
    for key, evidence in entries.items():
        assert evidence is not None
        assert evidence["content_sha256"] == digest(evidence["data"])
        assert evidence["source"].lower() == "https://api.github.com/repos/" + key
    clock_value = [
        max(datetime.fromisoformat(e["observed_at"]).timestamp() for e in entries.values()) + 10
    ]

    def clock():
        return clock_value[0]

    def cache():
        return GitHubCache(GitHubStore(dsn=dsn), clock=clock)

    def inspect(instance, key):
        return instance.inspect(
            REPOSITORY, key.removeprefix(REPOSITORY.lower()), read_cached_evidence
        )

    queries = []

    def query(label, sql, parameters=()):
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        queries.append({"label": label, "sql": sql, "rows": rows})
        return rows

    # A network call during seed admission is an error: all successful data is captured data.
    with patch.object(httpx.Client, "get", side_effect=AssertionError("Unexpected upstream call")):
        seeded = [inspect(cache(), key) for key in keys]
    assert all(item["cache_status"] == "fresh-cache" for item in seeded)
    assert query(
        "seed_inventory", "SELECT count(*),count(DISTINCT request_key) FROM pf_github_cache"
    )[0] == (31, 31)

    clock_value[0] += FRESH_SECONDS + 1
    calls = []
    call_lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()
    barrier = threading.Barrier(8)

    def recorded_response(_client, source, **_kwargs):
        with call_lock:
            calls.append({"kind": "recorded-200-replay", "source": source})
        entered.set()
        assert release.wait(15)
        return httpx.Response(
            200,
            json=entries[keys[0]]["data"],
            headers={"etag": entries[keys[0]]["etag"]} if entries[keys[0]].get("etag") else {},
        )

    def concurrent_read():
        instance = cache()
        barrier.wait(timeout=15)
        return inspect(instance, keys[0])

    with patch.object(httpx.Client, "get", recorded_response), ThreadPoolExecutor(8) as pool:
        futures = [pool.submit(concurrent_read) for _ in range(8)]
        try:
            assert entered.wait(15)
            deadline = time.monotonic() + 10
            while sum(f.done() for f in futures) < 7 and time.monotonic() < deadline:
                time.sleep(0.02)
            assert sum(f.done() for f in futures) == 7
            active_lease = query(
                "one_active_lease",
                "SELECT count(*),count(*) FILTER (WHERE owner<>''),"
                "min(tokens) FROM pf_github_refresh",
            )
            assert active_lease == [(1, 1, 7)]
        finally:
            release.set()
        parallel = [future.result(timeout=20) for future in futures]
    assert len(calls) == 1
    assert sorted(item["cache_status"] for item in parallel) == ["live"] + ["stale-busy"] * 7
    assert all(digest(item["data"]) == entries[keys[0]]["content_sha256"] for item in parallel)

    # Expire fresh validation, then use a CONTROLLED 429 rather than consume provider quota.
    clock_value[0] += FRESH_SECONDS + 1

    def rate_limited(_client, source, **_kwargs):
        calls.append({"kind": "controlled-429", "source": source, "retry_after": 120})
        return httpx.Response(429, headers={"retry-after": "120"})

    with patch.object(httpx.Client, "get", rate_limited):
        limited = inspect(cache(), keys[1])
        available = [inspect(cache(), key) for key in keys]
    assert limited["cache_status"] == "stale-rate-limit"
    assert limited["retry_after_seconds"] == 120
    assert len(calls) == 2
    assert all(item["cache_status"] == "stale-cooldown" for item in available)
    assert all(item["stale"] and item["retry_after_seconds"] == 120 for item in available)
    assert all(
        digest(item["data"]) == entries[key]["content_sha256"]
        for key, item in zip(keys, available, strict=True)
    )
    query(
        "shared_cooldown",
        "SELECT count(*),max(cooldown_until),max(lease_until),max(tokens) FROM pf_github_refresh",
    )

    restart()
    with patch.object(httpx.Client, "get", side_effect=AssertionError("Cooldown lost on restart")):
        after_restart = [inspect(cache(), key) for key in keys]
    assert all(item["cache_status"] == "stale-cooldown" for item in after_restart)

    # Virtual-clock lease expiry allows a second owner; old-owner completion must be fenced.
    clock_value[0] += 121
    first = cache()
    second = cache()
    assert first._claim(REPOSITORY, keys[2], entries[keys[2]], "old-owner")[0] == "fetch"
    assert second._claim(REPOSITORY, keys[3], entries[keys[3]], "new-owner")[0] == "busy"
    clock_value[0] += 31
    assert second._claim(REPOSITORY, keys[3], entries[keys[3]], "new-owner")[0] == "fetch"
    first._finish("old-owner", keys[2], entries[keys[2]])
    fence = query(
        "expired_owner_fenced", "SELECT owner,cooldown_until,lease_until FROM pf_github_refresh"
    )[0]
    assert fence[0] == "new-owner" and fence[1] <= clock() and fence[2] == clock() + 30
    old_checked = query(
        "old_owner_did_not_write",
        "SELECT checked_at FROM pf_github_cache WHERE request_key=%s",
        (keys[2],),
    )[0][0]
    assert old_checked == datetime.fromisoformat(entries[keys[2]]["observed_at"]).timestamp()
    # A late provider quota response is shared even when its payload ownership expired.
    first._finish("old-owner", keys[2], cooldown=999)
    assert query(
        "late_rate_limit_preserved",
        "SELECT owner,cooldown_until,lease_until FROM pf_github_refresh",
    )[0] == ("new-owner", clock() + 999, clock() + 30)
    second._finish("new-owner", keys[3], entries[keys[3]])
    assert query(
        "owner_released", "SELECT owner,lease_until,cooldown_until FROM pf_github_refresh"
    )[0] == ("", 0, clock() + 999)

    with psycopg.connect(dsn, connect_timeout=5) as connection:
        version = connection.execute("SHOW server_version").fetchone()[0]
        rows = connection.execute(
            "SELECT request_key,payload FROM pf_github_cache ORDER BY request_key"
        ).fetchall()
    assert len(rows) == 31
    provenance = []
    for key, payload in rows:
        stored = json.loads(payload)
        assert stored["source"] == entries[key]["source"]
        assert digest(stored["data"]) == entries[key]["content_sha256"]
        provenance.append(
            {
                "request_key": key,
                "source": entries[key]["source"],
                "source_observed_at": entries[key]["observed_at"],
                "source_content_sha256": entries[key]["content_sha256"],
                "persisted_content_sha256": digest(stored["data"]),
            }
        )
    return {
        "verified_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "database": {
            "engine": "native PostgreSQL",
            "version": version,
            "isolated_disposable_cluster": True,
            "real_restart_completed": True,
        },
        "source_bundle": str(BUNDLE.relative_to(ROOT)).replace("\\", "/"),
        "source_bundle_sha256": hashlib.sha256(BUNDLE.read_bytes()).hexdigest(),
        "network_github_requests": 0,
        "clock": "Virtual cache clock anchored to latest real capture + 10s; advances 601s, "
        "601s, 121s, 31s. PostgreSQL and parallel execution use real processes/time.",
        "seed": {"separate_cache_instances": 31, "real_responses": 31, "upstream_calls": 0},
        "parallel": {
            "separate_cache_instances": 8,
            "identical_requests": 8,
            "upstream_calls": 1,
            "statuses": [r["cache_status"] for r in parallel],
        },
        "cooldown": {
            "controlled_response": 429,
            "retry_after_seconds": 120,
            "other_view_reads": 31,
            "extra_upstream_calls": 0,
            "cached_views_available_after_real_restart": len(after_restart),
        },
        "lease": {
            "virtual_expiry_seconds": 31,
            "old_owner_completion_fenced": True,
            "new_owner_completed": True,
            "late_provider_cooldown_preserved": True,
        },
        "upstream_adapter_calls": calls,
        "native_sql_observations": queries,
        "provenance": provenance,
        "limits": [
            "Controlled recorded-200 replay and 429 response; no live provider fault.",
            "Eight threads with distinct cache/store instances share one native database; "
            "this is not a multi-host load test.",
            "Virtual-clock timestamps after seed admission are validation experiment times, "
            "not fresh GitHub captures. Original source capture times are retained above.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "evidence/github-shared-cache.json")
    args = parser.parse_args()
    with isolated_postgres(args.postgres_bin.resolve()) as (dsn, restart):
        report = verify(dsn, restart)
    report["database"]["cluster_stopped_and_removed"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": True,
                "real_responses": 31,
                "network_github_requests": 0,
                "parallel_upstream_calls": 1,
                "cached_views_during_cooldown": 31,
            }
        )
    )


if __name__ == "__main__":
    main()
