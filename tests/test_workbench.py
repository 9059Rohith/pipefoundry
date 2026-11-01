import json

import httpx
import pytest
from fastapi.testclient import TestClient

from pipefoundry.workbench import PAGES, AgentRequest, github, run_agent


@pytest.fixture(autouse=True)
def isolate_ai_configuration(monkeypatch):
    for name in (
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "PIPEFOUNDRY_AI_PROVIDER",
        "PIPEFOUNDRY_AI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "a" * 40)
    monkeypatch.setenv("PIPEFOUNDRY_SEED_DEMO", "false")
    from pipefoundry.api import create_app

    with TestClient(create_app(tmp_path)) as client:
        yield client


def test_public_validation_has_no_state_changes_and_rejects_unsafe_config(client, tmp_path):
    config = {"name": "hourly-orders", "schedule": "0 * * * *"}
    before = list(tmp_path.rglob("*"))
    response = client.post("/workbench/api/validate", json={"config": config})
    assert response.status_code == 200
    result = response.json()
    assert result["valid"] and "kind: CronJob" in result["manifest"]
    assert "not executed or deployed" in result["status"]
    assert before == list(tmp_path.rglob("*"))
    invalid = client.post(
        "/workbench/api/validate",
        json={
            "config": {**config, "output": {"path": "../../secret.db"}, "secret": "NEVER-REFLECT"}
        },
    )
    assert not invalid.json()["valid"]
    assert "NEVER-REFLECT" not in invalid.text
    assert client.post("/pipelines", json={"config": config}).status_code == 401
    assert (
        client.post(
            "/workbench/api/agent",
            json={"repo": "owner/repository", "question": "Inspect releases"},
        ).status_code
        == 401
    )


def test_public_input_body_limit_still_applies(client):
    assert client.post("/workbench/api/validate", content=b"x" * 32769).status_code == 413
    invalid = client.post("/workbench/api/validate", json={"config": "NEVER-REFLECT"})
    assert invalid.status_code == 422 and "NEVER-REFLECT" not in invalid.text
    assert client.get("/demo").status_code == 401
    assert client.get("/demo/console").status_code == 401
    assert client.get("/workbench/assets/../../api.py").status_code != 200


def test_github_network_adapter_projects_real_response_and_rejects_non_repo(monkeypatch):
    from pipefoundry import workbench

    workbench._cache.clear()
    calls = []

    def get(self, url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(200, json={"full_name": "octocat/Hello-World"})

    monkeypatch.setattr(httpx.Client, "get", get)
    result = github("octocat/Hello-World", "repository")
    assert result["data"]["full_name"] == "octocat/Hello-World"
    assert calls[0][0] == "https://api.github.com/repos/octocat/Hello-World"
    assert "Authorization" not in calls[0][1]["headers"]
    github("octocat/Hello-World", "repository")
    assert len(calls) == 1
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        github("http://169.254.169.254/latest", "repository")
    with pytest.raises(HTTPException):
        github("../..", "repository")


def test_missing_ai_credentials_is_explicit(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = client.post(
        "/workbench/api/agent",
        headers={"Authorization": "Bearer " + "a" * 40},
        json={"repo": "octocat/Hello-World", "question": "Inspect releases"},
    )
    assert result.status_code == 503
    assert "No AI request was made" in result.text


def test_agent_executes_only_readonly_tools_and_returns_trace(monkeypatch):
    from pipefoundry import workbench

    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    observed = []

    def post(self, url, **kwargs):
        observed.append(kwargs["json"])
        if len(observed) == 1:
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "function_call",
                            "id": "fc1",
                            "call_id": "call1",
                            "name": "inspect_github",
                            "arguments": json.dumps({"view": "runs"}),
                        }
                    ]
                },
            )
        assert kwargs["json"]["input"][-1]["call_id"] == "call1"
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "No workflow runs were returned."}
                        ],
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    monkeypatch.setattr(
        workbench,
        "github",
        lambda repo, view: {
            "data": {"workflow_runs": []},
            "source": "https://api.github.com/repos/a/b/actions/runs",
            "observed_at": "2026-11-01T00:00:00Z",
        },
    )
    result = run_agent(AgentRequest(repo="a/b", question="Inspect recent failures"))
    assert result["answer"] == "No workflow runs were returned."
    assert result["trace"][0]["view"] == "runs"
    assert observed[0]["store"] is False
    assert len(observed) == 2


def test_agent_stops_unsupported_tool(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda *args, **kwargs: httpx.Response(
            200,
            json={
                "output": [{"type": "function_call", "name": "execute_shell", "arguments": "{}"}]
            },
        ),
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        run_agent(AgentRequest(repo="a/b", question="Deploy this repository"))
    assert error.value.status_code == 422


def test_every_workbench_route_is_public_and_has_security_headers(client):
    for page in PAGES:
        response = client.get("/workbench/" + page)
        assert response.status_code == 200
        assert f'data-page="{page}"' in response.text
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/").status_code == 200
    assert client.get("/workbench/assets/app.css").status_code == 200
    assert client.get("/workbench/assets/app.js").status_code == 200


def test_gemini_roundtrips_original_tool_signatures_and_evidence(monkeypatch, client):
    from pipefoundry import workbench

    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-only")
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "inspect_github", "arguments": '{"view":"repository"}'},
                "extra_content": {"google": {"thought_signature": "opaque-unit-test-signature"}},
            }
        ],
        "extra_content": {"metadata": "preserve"},
    }
    requests = []

    def post(self, url, **kwargs):
        requests.append(kwargs["json"])
        assert url == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        if len(requests) == 1:
            output = message
        else:
            assert kwargs["json"]["messages"][-2] == message
            assert kwargs["json"]["messages"][-1]["tool_call_id"] == "call-1"
            output = {"role": "assistant", "content": "The repository default branch is main."}
        return httpx.Response(200, json={"id": "response-1", "choices": [{"message": output}]})

    monkeypatch.setattr(httpx.Client, "post", post)
    monkeypatch.setattr(
        workbench,
        "github",
        lambda repo, view: {
            "data": {"default_branch": "main"},
            "source": "https://api.github.com/repos/a/b",
            "observed_at": "2026-11-02T00:00:00Z",
        },
    )
    result = run_agent(AgentRequest(repo="a/b", question="Inspect repository metadata"))
    assert result["provider"] == "gemini"
    assert result["model"] == "gemini-3.5-flash-lite"
    assert result["trace"][0]["view"] == "repository"
    assert len(requests) == 2
    state = client.get("/workbench/api/integrations").json()
    assert state["ai_provider"] == "gemini" and state["ai_configured"]
    assert "unit-test-only" not in json.dumps(state)


def test_gemini_free_quota_retries_once_without_paid_fallback(monkeypatch):
    from fastapi import HTTPException

    from pipefoundry import workbench

    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-only")
    calls = []
    monkeypatch.setattr(workbench.time, "sleep", lambda seconds: None)

    def post(self, url, **kwargs):
        calls.append(url)
        return httpx.Response(429)

    monkeypatch.setattr(httpx.Client, "post", post)
    with pytest.raises(HTTPException) as error:
        run_agent(AgentRequest(repo="a/b", question="Inspect repository metadata"))
    assert error.value.status_code == 429
    assert "no paid fallback" in error.value.detail
    assert len(calls) == 2 and all("googleapis.com" in url for url in calls)


def test_gemini_rejects_unsupported_tools_and_ungrounded_answers(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("GEMINI_API_KEY", "unit-test-only")
    for message in [
        {"role": "assistant", "content": "An ungrounded answer"},
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call-1", "function": {"name": "execute_shell", "arguments": "{}"}}
            ],
        },
    ]:
        monkeypatch.setattr(
            httpx.Client,
            "post",
            lambda *args, response_message=message, **kwargs: httpx.Response(
                200, json={"choices": [{"message": response_message}]}
            ),
        )
        with pytest.raises(HTTPException):
            run_agent(AgentRequest(repo="a/b", question="Inspect repository metadata"))


@pytest.mark.parametrize("age,expect_stale", [(30, False), (300, True)])
def test_real_cached_github_evidence_survives_rate_limits(monkeypatch, age, expect_stale):
    from datetime import UTC, datetime, timedelta

    from pipefoundry import workbench

    workbench._cache.clear()
    observed = (datetime.now(UTC) - timedelta(seconds=age)).isoformat()
    evidence = {
        "data": {"default_branch": "main"},
        "observed_at": observed,
        "source": "https://api.github.com/repos/a/b",
        "stale": False,
    }
    monkeypatch.setattr(workbench, "read_cached_evidence", lambda key: evidence)
    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: httpx.Response(429))
    result = github("a/b", "repository")
    assert result["stale"] is expect_stale
    assert result["observed_at"] == observed
    assert result["data"] == evidence["data"]
    if expect_stale:
        assert result["cache_status"] == "stale-rate-limit"
        assert "previously fetched" in result["warning"]


def test_github_rejects_expired_cache_and_reports_retry(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from fastapi import HTTPException

    from pipefoundry import workbench

    workbench._cache.clear()
    observed = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    monkeypatch.setattr(
        workbench,
        "read_cached_evidence",
        lambda key: {"data": {"default_branch": "main"}, "observed_at": observed},
    )
    monkeypatch.setattr(httpx.Client, "get", lambda *args, **kwargs: httpx.Response(429))
    with pytest.raises(HTTPException) as error:
        github("a/b", "repository")
    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "60"
    assert "no usable cached evidence" in error.value.detail
