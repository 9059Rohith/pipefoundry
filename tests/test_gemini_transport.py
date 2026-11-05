"""Transport failures must never reset the read-only agent's request budget."""

import logging

import httpx
import pytest
from fastapi import HTTPException

from pipefoundry import workbench

TOOL = {
    "role": "assistant",
    "tool_calls": [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "inspect_github", "arguments": '{"view":"repository"}'},
        }
    ],
}
ANSWER = {"role": "assistant", "content": "The default branch is main."}


@pytest.fixture
def transport(monkeypatch):
    now = [100.0]
    waits, requests = [], []
    outcomes = []

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    def post(self, url, **kwargs):
        requests.append((url, kwargs, now[0]))
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict):
            return httpx.Response(200, json={"choices": [{"message": outcome}]})
        return outcome

    monkeypatch.setattr(workbench.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(workbench.time, "time", lambda: 1793880000)
    monkeypatch.setattr(workbench.time, "sleep", sleep)
    monkeypatch.setattr(httpx.Client, "post", post)
    monkeypatch.setattr(
        workbench,
        "github",
        lambda *args: {
            "data": {"default_branch": "main"},
            "source": "https://api.github.com/repos/a/b",
            "observed_at": "2026-11-05T00:00:00Z",
            "stale": True,
        },
    )
    return outcomes, requests, waits, now


def analyze(**kwargs):
    return workbench.run_gemini_agent(
        workbench.AgentRequest(repo="a/b", question="Inspect repository metadata"),
        "test-secret-do-not-log",
        "gemini-3.5-flash-lite",
        **kwargs,
    )


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_transient_status_recovers_real_grounded_answer(transport, status):
    outcomes, requests, waits, _ = transport
    outcomes.extend([httpx.Response(status), TOOL, ANSWER])
    result = analyze()
    assert result["answer"].endswith(ANSWER["content"])
    assert result["answer"].startswith("**Dated evidence:**")
    assert result["trace"][0]["source"] == "https://api.github.com/repos/a/b"
    assert len(requests) == 3
    assert waits == [1]
    assert all("googleapis.com" in request[0] for request in requests)


@pytest.mark.parametrize("failure", [httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError])
def test_network_failure_recovers_without_logging_sensitive_exception(transport, caplog, failure):
    outcomes, _, waits, _ = transport
    outcomes.extend([failure("test-secret-do-not-log user question body"), TOOL, ANSWER])
    with caplog.at_level(logging.WARNING):
        assert analyze()["trace"]
    assert waits == [1]
    assert failure.__name__ in caplog.text
    assert "test-secret" not in caplog.text and "user question" not in caplog.text


def test_retries_are_shared_across_model_tool_turns(transport, caplog):
    outcomes, requests, waits, _ = transport
    outcomes.extend([httpx.Response(503), TOOL, httpx.Response(502), httpx.Response(504)])
    with caplog.at_level(logging.WARNING), pytest.raises(HTTPException) as error:
        analyze()
    assert error.value.status_code == 503
    assert waits == [1, 2]
    assert len(requests) == 4
    assert "503" in caplog.text and "504" in caplog.text


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_configuration_and_other_client_errors_never_retry(transport, status):
    outcomes, requests, waits, _ = transport
    outcomes.append(httpx.Response(status, text="private provider error body"))
    with pytest.raises(HTTPException) as error:
        analyze()
    assert error.value.status_code == 502
    assert "private" not in error.value.detail
    assert len(requests) == 1 and not waits


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("retry_after", ["120", "Thu, 05 Nov 2026 12:02:00 GMT"])
def test_long_retry_after_propagates_without_retrying_early(transport, status, retry_after):
    outcomes, requests, waits, _ = transport
    outcomes.append(httpx.Response(status, headers={"Retry-After": retry_after}))
    with pytest.raises(HTTPException) as error:
        analyze()
    assert error.value.status_code == (429 if status == 429 else 503)
    assert error.value.headers["Retry-After"] == retry_after
    assert len(requests) == 1 and not waits


@pytest.mark.parametrize("retry_after", ["nonsense", "nan", "inf", "-1"])
def test_invalid_retry_after_uses_bounded_backoff(transport, retry_after):
    outcomes, _, waits, _ = transport
    outcomes.extend([httpx.Response(503, headers={"Retry-After": retry_after}), TOOL, ANSWER])
    assert analyze()["trace"]
    assert waits == [1]


def test_short_retry_after_is_respected(transport):
    outcomes, _, waits, _ = transport
    outcomes.extend([httpx.Response(503, headers={"Retry-After": "2"}), TOOL, ANSWER])
    assert analyze()["trace"]
    assert waits == [2]


def test_deadline_is_shared_and_bounds_next_request_timeout(transport, monkeypatch):
    outcomes, requests, waits, now = transport
    original_github = workbench.github

    def github(*args):
        now[0] += 55
        return original_github(*args)

    monkeypatch.setattr(workbench, "github", github)
    outcomes.extend([TOOL, httpx.Response(503), ANSWER])
    assert analyze()["trace"]
    assert waits == [1]
    assert requests[1][1]["timeout"] == 5
    assert requests[2][1]["timeout"] == 4


def test_deadline_stops_http_after_slow_evidence(transport, monkeypatch):
    outcomes, requests, waits, now = transport
    original_github = workbench.github

    def github(*args):
        now[0] += 60
        return original_github(*args)

    monkeypatch.setattr(workbench, "github", github)
    outcomes.extend([TOOL, ANSWER])
    with pytest.raises(HTTPException) as error:
        analyze()
    assert error.value.status_code == 503
    assert len(requests) == 1 and not waits


def test_retry_cannot_outlive_remaining_deadline(transport, monkeypatch):
    outcomes, requests, waits, now = transport
    original_github = workbench.github

    def github(*args):
        now[0] += 59.5
        return original_github(*args)

    monkeypatch.setattr(workbench, "github", github)
    outcomes.extend([TOOL, httpx.Response(503), ANSWER])
    with pytest.raises(HTTPException) as error:
        analyze()
    assert error.value.status_code == 503
    assert len(requests) == 2 and not waits


def test_http_request_ceiling_applies_even_if_turn_loop_grows(transport):
    outcomes, requests, _, _ = transport
    outcomes.extend([ANSWER] * 7)
    budget = workbench._GeminiBudget()
    with httpx.Client() as client:
        for _ in range(6):
            workbench._gemini_request(client, key="test-only", payload={}, budget=budget)
        with pytest.raises(HTTPException) as error:
            workbench._gemini_request(client, key="test-only", payload={}, budget=budget)
    assert error.value.status_code == 503
    assert len(requests) == 6


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_first_turn_final_retry_uses_fixed_free_model_for_rest_of_conversation(transport, status):
    outcomes, requests, waits, _ = transport
    outcomes.extend([httpx.Response(status), httpx.Response(status), TOOL, ANSWER])
    result = analyze(allow_free_fallback=True)
    assert result["model"] == "gemini-3.1-flash-lite"
    assert result["trace"] and result["answer"].startswith("**Dated evidence:**")
    assert [request[1]["json"]["model"] for request in requests] == [
        "gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
    ]
    assert waits == [1, 2]
    assert len({request[0] for request in requests}) == 1
    assert len({request[1]["headers"]["Authorization"] for request in requests}) == 1


def test_fallback_failure_exhausts_same_retry_budget_and_logs_actual_model(transport, caplog):
    outcomes, requests, waits, _ = transport
    outcomes.extend([httpx.Response(503, text="private body")] * 3)
    with caplog.at_level(logging.WARNING), pytest.raises(HTTPException) as error:
        analyze(allow_free_fallback=True)
    assert error.value.status_code == 503
    assert waits == [1, 2] and len(requests) == 3
    assert "model=gemini-3.1-flash-lite" in caplog.text
    assert "attempt=3" in caplog.text and "phase=initial" in caplog.text
    assert "private body" not in caplog.text and "test-secret" not in caplog.text


def test_no_model_switch_after_first_assistant_tool_call(transport, caplog):
    outcomes, requests, _, _ = transport
    signed_tool = {**TOOL, "extra_content": {"thought_signature": "opaque-test-only"}}
    outcomes.extend([signed_tool, httpx.Response(503), httpx.Response(503), ANSWER])
    with caplog.at_level(logging.WARNING):
        result = analyze(allow_free_fallback=True)
    assert result["model"] == "gemini-3.5-flash-lite"
    assert all(request[1]["json"]["model"] == "gemini-3.5-flash-lite" for request in requests)
    assert requests[-1][1]["json"]["messages"][2] == signed_tool
    assert "phase=followup" in caplog.text
    assert "opaque-test-only" not in caplog.text


@pytest.mark.parametrize("first", [429, "network"])
def test_quota_or_network_failures_do_not_trigger_model_fallback(transport, first):
    outcomes, requests, _, _ = transport
    first_failure = httpx.Response(429) if first == 429 else httpx.ConnectError("test-only")
    second_failure = httpx.Response(503) if first == 429 else httpx.ConnectError("test-only")
    outcomes.extend([first_failure, second_failure, TOOL, ANSWER])
    assert analyze(allow_free_fallback=True)["model"] == "gemini-3.5-flash-lite"
    assert all(request[1]["json"]["model"] == "gemini-3.5-flash-lite" for request in requests)


def test_long_retry_after_stops_before_free_fallback(transport):
    outcomes, requests, waits, _ = transport
    outcomes.extend([httpx.Response(503), httpx.Response(503, headers={"Retry-After": "120"})])
    with pytest.raises(HTTPException) as error:
        analyze(allow_free_fallback=True)
    assert error.value.headers["Retry-After"] == "120"
    assert waits == [1] and len(requests) == 2
    assert all(request[1]["json"]["model"] == "gemini-3.5-flash-lite" for request in requests)


def test_operator_agent_does_not_enable_model_fallback_by_default(transport):
    outcomes, requests, _, _ = transport
    outcomes.extend([httpx.Response(503), httpx.Response(503), TOOL, ANSWER])
    assert analyze()["model"] == "gemini-3.5-flash-lite"
    assert all(request[1]["json"]["model"] == "gemini-3.5-flash-lite" for request in requests)


def test_fallback_cannot_change_an_arbitrary_configured_model(transport, caplog):
    outcomes, requests, _, _ = transport
    outcomes.extend([httpx.Response(503), httpx.Response(503), TOOL, ANSWER])
    with caplog.at_level(logging.WARNING):
        result = workbench.run_gemini_agent(
            workbench.AgentRequest(repo="a/b", question="Inspect repository metadata"),
            "test-only-key",
            "configured-secret-model",
            allow_free_fallback=True,
        )
    assert result["model"] == "configured-secret-model"
    assert all(request[1]["json"]["model"] == "configured-secret-model" for request in requests)
    assert "configured-secret-model" not in caplog.text
