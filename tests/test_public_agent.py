import concurrent.futures
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from pipefoundry.workbench import run_gemini_agent as real_gemini_agent


def test_persistent_buckets_are_atomic_and_survive_restart(tmp_path):
    from pipefoundry.public_demo import DemoLimiter

    path = tmp_path / "quota.db"

    def attempt(index):
        try:
            DemoLimiter(sqlite_path=path).consume(f"hashed-client-{index}", now=1000)
            return True
        except HTTPException as exc:
            assert exc.status_code == 429
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 2
    with pytest.raises(HTTPException) as error:
        DemoLimiter(sqlite_path=path).consume("new-client-after-restart", now=1001)
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) > 0


def test_client_and_daily_limits_persist(tmp_path):
    from pipefoundry.public_demo import DemoLimiter

    path = tmp_path / "quota.db"
    for minute in range(3):
        DemoLimiter(sqlite_path=path).consume("same-client", now=1000 + 60 * minute)
    with pytest.raises(HTTPException) as error:
        DemoLimiter(sqlite_path=path).consume("same-client", now=1180)
    assert error.value.status_code == 429
    daily_path = tmp_path / "daily.db"
    for index in range(30):
        DemoLimiter(sqlite_path=daily_path).consume(f"client-{index}", now=1000 + 60 * index)
    with pytest.raises(HTTPException):
        DemoLimiter(sqlite_path=daily_path).consume("last-client", now=3000)


@pytest.fixture
def public_client(tmp_path, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("PIPEFOUNDRY_METADATA_DSN", raising=False)
    monkeypatch.setenv("PIPEFOUNDRY_DEMO_LIMIT_DB", str(tmp_path / "limits.db"))
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "test-private-control-token-" * 2)
    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-key")
    monkeypatch.setenv("PIPEFOUNDRY_SEED_DEMO", "false")
    from pipefoundry import workbench
    from pipefoundry.api import create_app

    calls = []

    def provider(body, key, model, **kwargs):
        calls.append((body, kwargs))
        return {
            "answer": "A unit-test transport response",
            "trace": [{"tool": "inspect_github", "source": "https://api.github.com/repos/a/b"}],
            "model": model,
            "provider": "gemini",
        }

    monkeypatch.setattr(workbench, "run_gemini_agent", provider)
    with TestClient(create_app(tmp_path / "platform")) as client:
        yield client, calls


def test_anonymous_demo_stops_inference_at_quota_and_protects_private_api(public_client):
    client, calls = public_client
    body = {"question": "Inspect the default branch and language."}
    for spoofed in ["198.51.100.1", "198.51.100.2"]:
        result = client.post(
            "/workbench/api/demo-agent", json=body, headers={"X-Forwarded-For": spoofed}
        )
        assert result.status_code == 200
    result = client.post(
        "/workbench/api/demo-agent", json=body, headers={"X-Forwarded-For": "198.51.100.3"}
    )
    assert result.status_code == 429 and result.headers["Retry-After"]
    assert len(calls) == 2
    assert all(call[0].repo == "9059Rohith/pipefoundry" for call in calls)
    assert calls[0][1]["max_output_tokens"] == 600
    assert calls[0][1]["allow_free_fallback"] is True
    assert client.post("/workbench/api/agent", json={**body, "repo": "a/b"}).status_code == 401
    assert client.post("/pipelines", json={}).status_code == 401
    assert client.post("/releases/apply", json={}).status_code == 401


def test_public_input_and_origin_reject_before_provider(public_client):
    client, calls = public_client
    for payload in [
        {"question": "x" * 601},
        {"question": "Inspect metadata", "repo": "a/b"},
        {"question": "Inspect metadata", "model": "paid-model"},
    ]:
        assert client.post("/workbench/api/demo-agent", json=payload).status_code == 422
    response = client.post(
        "/workbench/api/demo-agent",
        json={"question": "Inspect metadata"},
        headers={"Origin": "https://attacker.invalid"},
    )
    assert response.status_code == 403 and not calls
    assert (
        client.post(
            "/workbench/api/demo-agent",
            json={"question": "Inspect metadata"},
            headers={"Origin": "http://testserver"},
        ).status_code
        == 200
    )


def test_limiter_fail_closed_in_vercel(public_client, monkeypatch):
    client, calls = public_client
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("PIPEFOUNDRY_METADATA_DSN", raising=False)
    assert (
        client.post("/workbench/api/demo-agent", json={"question": "Inspect metadata"}).status_code
        == 503
    )
    assert not calls


def test_address_hash_ignores_untrusted_forwarding_and_never_stores_ip(tmp_path, monkeypatch):
    from starlette.requests import Request

    from pipefoundry.public_demo import DemoLimiter, client_identity

    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "private-secret-" * 4)
    monkeypatch.delenv("VERCEL", raising=False)

    def request(header):
        return Request(
            {
                "type": "http",
                "headers": [(b"x-forwarded-for", header.encode())],
                "client": ("203.0.113.7", 123),
                "scheme": "https",
                "path": "/",
            }
        )

    baseline = client_identity(request("198.51.100.3"))
    assert baseline == client_identity(request("198.51.100.4"))
    monkeypatch.setenv("VERCEL", "1")
    assert client_identity(request("198.51.100.3")) != baseline
    assert client_identity(request("198.51.100.3, 198.51.100.4")) == baseline
    path = tmp_path / "addresses.db"
    DemoLimiter(sqlite_path=path).consume(baseline, now=1000)
    with sqlite3.connect(path) as db:
        rows = repr(db.execute("SELECT * FROM pf_public_ai_limits").fetchall())
    assert "203.0.113.7" not in rows and "198.51.100.3" not in rows


def test_database_failure_stops_public_inference(public_client, monkeypatch):
    import psycopg

    from pipefoundry import public_demo

    client, calls = public_client
    monkeypatch.setenv("PIPEFOUNDRY_METADATA_DSN", "not-a-real-dsn")

    def disconnected(*args, **kwargs):
        raise psycopg.OperationalError("unit-test database unavailable")

    monkeypatch.setattr(public_demo.psycopg, "connect", disconnected)
    result = client.post("/workbench/api/demo-agent", json={"question": "Inspect metadata"})
    assert result.status_code == 503 and not calls
    assert "not-a-real-dsn" not in result.text


@pytest.mark.parametrize("initial_failures", [0, 1, 2])
def test_anonymous_endpoint_runs_genuine_provider_tool_protocol(
    public_client, monkeypatch, initial_failures
):
    import httpx

    from pipefoundry import workbench

    client, _ = public_client
    monkeypatch.setenv("PIPEFOUNDRY_AI_MODEL", "paid-model-must-not-reach-public-route")
    monkeypatch.setattr(workbench.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(workbench, "run_gemini_agent", real_gemini_agent)
    messages = []

    def post(self, url, **kwargs):
        assert "generativelanguage.googleapis.com" in url
        messages.append(kwargs["json"])
        assert kwargs["json"]["max_tokens"] == 600
        if len(messages) <= initial_failures:
            return httpx.Response(503)
        if len(messages) == initial_failures + 1:
            message = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "public-call",
                        "type": "function",
                        "function": {
                            "name": "inspect_github",
                            "arguments": '{"view":"repository"}',
                        },
                        "extra_content": {"google": {"thought_signature": "unit-test-only"}},
                    }
                ],
            }
        else:
            assert kwargs["json"]["messages"][-1]["tool_call_id"] == "public-call"
            message = {"role": "assistant", "content": "The default branch is main."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    monkeypatch.setattr(httpx.Client, "post", post)
    monkeypatch.setattr(
        workbench,
        "github",
        lambda repo, view: {
            "data": {"default_branch": "main"},
            "source": "https://api.github.com/repos/9059Rohith/pipefoundry",
            "observed_at": "2026-11-01T18:50:10Z",
            "stale": True,
            "cache_status": "stale-rate-limit",
        },
    )
    result = client.request(
        "POST", "/workbench/api/demo-agent", json={"question": "Inspect metadata"}
    )
    assert result.status_code == 200 and result.json()["public_demo"]
    assert result.json()["trace"][0]["stale"] is True
    assert len(messages) == initial_failures + 2
    expected_model = "gemini-3.1-flash-lite" if initial_failures else "gemini-3.5-flash-lite"
    assert result.json()["model"] == expected_model
    assert messages[-1]["model"] == expected_model
    assert [item["model"] for item in messages] == (
        ["gemini-3.5-flash-lite"] + [expected_model] * (initial_failures + 1)
    )
    assert all("paid-model" not in item["model"] for item in messages)
    public_status = client.get("/workbench/api/integrations").json()["public_ai"]
    assert public_status["preferred_model"] == "gemini-3.5-flash-lite"
    assert public_status["fallback_model"] == "gemini-3.1-flash-lite"
