import json
import sys

import pytest
from test_platform import config


def test_cluster_status_and_logs_read_live_state_with_bounded_arguments(tmp_path, monkeypatch):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    platform = Platform(tmp_path)
    calls = []

    def execute(args, log, timeout=180):
        calls.append(args)
        if "logs" in args:
            return "worker: completed 3 rows"
        return json.dumps(
            {
                "spec": {"suspend": False},
                "status": {
                    "lastScheduleTime": "2026-01-01T00:00:00Z",
                    "active": [{"name": "orders-1"}],
                },
            }
        )

    monkeypatch.setattr(platform, "_kubectl", lambda: "kubectl")
    monkeypatch.setattr(platform, "_execute", execute)
    platform.deploy(Pipeline.model_validate(config()), "kubernetes")
    status = platform.status("orders-demo", refresh=True)
    assert status["cluster"]["active_jobs"] == 1
    assert status["cluster"]["last_schedule_time"] == "2026-01-01T00:00:00Z"
    assert platform.logs("orders-demo") == ["worker: completed 3 rows"]
    assert calls[-1] == [
        "kubectl",
        "-n",
        "pipefoundry",
        "logs",
        "-l",
        "pipeline=orders-demo",
        "--all-containers=true",
        "--tail=200",
        "--limit-bytes=65536",
        "--prefix=true",
        "--max-log-requests=5",
    ]


@pytest.mark.parametrize("next_state", ["render", "local", "failed"])
def test_teardown_removes_prior_cluster_resources_after_latest_revision_changes(
    tmp_path, monkeypatch, next_state
):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    platform = Platform(tmp_path)
    execute_real_worker = platform._execute
    calls = []

    def execute(args, log, timeout=180):
        if args[0] == sys.executable:
            return execute_real_worker(args, log, timeout)
        calls.append(args)
        return "{}"

    monkeypatch.setattr(platform, "_kubectl", lambda: "kubectl")
    monkeypatch.setattr(platform, "_execute", execute)
    monkeypatch.setenv("PIPEFOUNDRY_NAMESPACE", "team-original")
    pipeline = Pipeline.model_validate(config())
    platform.deploy(pipeline, "kubernetes")
    # A later artifact or local execution must not erase a cluster-side workload.
    monkeypatch.setenv("PIPEFOUNDRY_NAMESPACE", "team-current")
    if next_state == "render":
        platform.render(pipeline)
    elif next_state == "local":
        platform.deploy(pipeline, "local")
    else:
        monkeypatch.delenv("PIPEFOUNDRY_POSTGRES_DSN", raising=False)
        failing = Pipeline.model_validate(config(output={"connector": "postgres"}))
        with pytest.raises(RuntimeError):
            platform.deploy(failing, "local")
    platform = Platform(tmp_path)
    monkeypatch.setattr(platform, "_kubectl", lambda: "kubectl")
    monkeypatch.setattr(platform, "_execute", execute)
    assert platform.status("orders-demo")["cluster_targets"] == [
        {"namespace": "team-original", "last_attempted_revision": 1}
    ]
    result = platform.teardown("orders-demo")
    assert result["status"] == "torn_down"
    assert result["cluster_targets"] == []
    deletes = [args for args in calls if "delete" in args]
    assert deletes == [
        [
            "kubectl",
            "-n",
            "team-original",
            "delete",
            "cronjob,job,configmap",
            "-l",
            "pipeline=orders-demo",
            "--ignore-not-found=true",
        ]
    ]


def test_partial_cluster_failure_preserves_targets_until_each_namespace_deleted(
    tmp_path, monkeypatch
):
    from pipefoundry.engine import Platform
    from pipefoundry.models import Pipeline

    platform = Platform(tmp_path)
    deletes = []
    fail_delete = True

    def execute(args, log, timeout=180):
        nonlocal fail_delete
        namespace = args[2]
        if "apply" in args and namespace == "team-b":
            raise RuntimeError("partially applied deployment")
        if "delete" in args:
            deletes.append(namespace)
            if namespace == "team-b" and fail_delete:
                fail_delete = False
                raise RuntimeError("temporary deletion failure")
        return "{}"

    monkeypatch.setattr(platform, "_kubectl", lambda: "kubectl")
    monkeypatch.setattr(platform, "_execute", execute)
    pipeline = Pipeline.model_validate(config())
    monkeypatch.setenv("PIPEFOUNDRY_NAMESPACE", "team-a")
    platform.deploy(pipeline, "kubernetes")
    monkeypatch.setenv("PIPEFOUNDRY_NAMESPACE", "team-b")
    with pytest.raises(RuntimeError, match="partially"):
        platform.deploy(pipeline, "kubernetes")
    platform.render(pipeline)
    monkeypatch.setenv("PIPEFOUNDRY_NAMESPACE", "team-unused")
    with pytest.raises(RuntimeError, match="temporary"):
        platform.teardown("orders-demo")
    state = platform.status("orders-demo")
    assert state["status"] != "torn_down"
    assert state["cluster_targets"] == [{"namespace": "team-b", "last_attempted_revision": 2}]
    assert platform.teardown("orders-demo")["cluster_targets"] == []
    assert deletes == ["team-a", "team-b", "team-b"]
