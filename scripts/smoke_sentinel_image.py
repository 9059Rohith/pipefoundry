"""Exercise actual HTTP + worker execution in the native minimal Sentinel image."""

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    image = os.environ.get("PIPEFOUNDRY_SENTINEL_IMAGE", "pipefoundry:sentinel")
    name = "pipefoundry-sentinel-smoke-" + secrets.token_hex(4)
    token = secrets.token_urlsafe(32)
    environment = {**os.environ, "PIPEFOUNDRY_API_TOKEN": token}
    container = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--memory=384m",
            "--cpus=1",
            "--pids-limit=64",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001",
            "--tmpfs",
            "/state:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001",
            "-p",
            "127.0.0.1::8080",
            "--env",
            "PIPEFOUNDRY_API_TOKEN",
            image,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert container.stdout.strip()
    try:
        mapping = subprocess.run(
            ["docker", "port", name, "8080"], capture_output=True, text=True, check=True
        ).stdout.strip()
        base = "http://" + mapping

        def request(path, body=None, authenticated=True):
            headers = {"Content-Type": "application/json"}
            if authenticated:
                headers["Authorization"] = "Bearer " + token
            data = json.dumps(body).encode() if body is not None else None
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(base + path, data=data, headers=headers), timeout=30
                ) as reply:
                    return reply.status, json.load(reply)
            except urllib.error.HTTPError as exc:
                return exc.code, json.load(exc)

        for _attempt in range(100):
            try:
                status, _ = request("/health/ready")
                if status == 200:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("native image did not become ready")
        body = {
            "config": {"name": "native-sentinel", "schedule": "0 * * * *"},
            "policy": {"allowed_operation": "create", "max_input_rows": 3},
        }
        unauthenticated, _ = request("/releases/plan", body, authenticated=False)
        assert unauthenticated == 401
        status, plan = request("/releases/plan", body)
        assert status == 200, plan
        apply = {
            "plan_id": plan["plan_id"],
            "digest": plan["digest"],
            "idempotency_key": "native-sentinel-001",
        }
        status, receipt = request("/releases/apply", apply)
        assert status == 200 and receipt["state"] == "succeeded", receipt
        status, retried = request("/releases/apply", apply)
        assert status == 200 and retried == receipt
        _, pipeline = request("/pipelines/native-sentinel")
        _, logs = request("/pipelines/native-sentinel/logs")
        assert pipeline["revision"] == 1
        worker = json.loads(logs["logs"][0])
        assert worker["rows"] == 3 and worker["quality"]["invalid_rows"] == 0
        runtime = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "python",
                "-c",
                "import json,os,sys,shutil; print(json.dumps({'python':sys.version,"
                "'uid':os.getuid(),'binaries':{n:shutil.which(n) for n in "
                "['sh','bash','mount','umount','pip','apt','apk']}}))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        inventory = json.loads(runtime.stdout)
        assert inventory["uid"] == 10001
        assert all(value is None for value in inventory["binaries"].values())
        report = {
            "image": image,
            "runtime": inventory,
            "unauthenticated_plan": 401,
            "plan_operation": plan["operation"],
            "receipt_state": receipt["state"],
            "revision": pipeline["revision"],
            "retry_same_receipt": retried == receipt,
            "worker": worker,
            "scope": "local native image; no hosted deployment",
        }
        output = root / "evidence" / "sentinel-native-http.json"
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
