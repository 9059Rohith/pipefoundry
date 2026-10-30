"""Scriptable JSON CLI; credentials stay in operator environment variables."""

import argparse
import json
import os
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline
from pipefoundry.release_models import RolloutPolicy
from pipefoundry.releases import ReleaseSentinel, digest


def load(path: str) -> Pipeline:
    source = Path(path)
    if source.stat().st_size > 32768:
        raise ValueError("pipeline config exceeds 32 KiB")
    return Pipeline.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


def review_plan(path: str) -> dict:
    source = Path(path)
    if source.stat().st_size > 32768:
        raise ValueError("review plan exceeds 32 KiB")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
        identity = document.pop("digest")
        if digest(document) != identity:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("review plan integrity check failed") from None
    return {**document, "digest": identity}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PipeFoundry pipeline lifecycle")
    parser.add_argument(
        "--state-dir", default=os.environ.get("PIPEFOUNDRY_STATE_DIR", ".pipefoundry")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "render", "deploy", "preview", "plan"):
        command = commands.add_parser(name)
        command.add_argument("config")
        if name in {"deploy", "preview", "plan"}:
            command.add_argument("--executor", choices=["local", "kubernetes"], default="local")
        if name == "plan":
            command.add_argument("--allow-operation", choices=["create", "update", "no-op"])
            command.add_argument("--max-cpu-millis", type=int, default=4000)
            command.add_argument("--max-memory-mib", type=int, default=8192)
            command.add_argument("--max-input-rows", type=int, default=10000)
            command.add_argument("--ttl-seconds", type=int, default=300)
    apply = commands.add_parser("apply")
    apply.add_argument("plan")
    apply.add_argument("--idempotency-key", required=True)
    receipt = commands.add_parser("receipt")
    receipt.add_argument("idempotency_key")
    recover = commands.add_parser("recover-release")
    recover.add_argument("idempotency_key")
    recover.add_argument("--confirm-worker-stopped", action="store_true", required=True)
    commands.add_parser("list")
    for name in ("status", "logs", "audit", "teardown", "backfill", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("name")
        if name == "backfill":
            command.add_argument("--start", required=True)
            command.add_argument("--end", required=True)
        if name == "rollback":
            command.add_argument("--revision", required=True, type=int)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "validate":
            result = {"valid": True, "config": load(arguments.config).model_dump()}
        else:
            platform = Platform(arguments.state_dir)
            match arguments.command:
                case "render":
                    result = platform.render(load(arguments.config))
                case "deploy":
                    result = platform.deploy(load(arguments.config), arguments.executor)
                case "preview":
                    result = platform.preview(load(arguments.config), arguments.executor)
                case "plan":
                    policy = RolloutPolicy(
                        allowed_operation=arguments.allow_operation,
                        max_cpu_millis=arguments.max_cpu_millis,
                        max_memory_mib=arguments.max_memory_mib,
                        max_input_rows=arguments.max_input_rows,
                    )
                    result = ReleaseSentinel(platform).plan(
                        load(arguments.config),
                        arguments.executor,
                        policy=policy,
                        ttl_seconds=arguments.ttl_seconds,
                    )
                case "apply":
                    plan = review_plan(arguments.plan)
                    result = ReleaseSentinel(platform).apply(
                        plan["plan_id"], plan["digest"], arguments.idempotency_key
                    )
                case "receipt":
                    result = ReleaseSentinel(platform).receipt(arguments.idempotency_key)
                case "recover-release":
                    result = ReleaseSentinel(platform).recover(
                        arguments.idempotency_key,
                        confirm_worker_stopped=arguments.confirm_worker_stopped,
                    )
                case "list":
                    result = platform.list()
                case "status":
                    result = platform.status(arguments.name, refresh=True)
                case "backfill":
                    result = platform.backfill(arguments.name, arguments.start, arguments.end)
                case "rollback":
                    result = platform.rollback(arguments.name, arguments.revision)
                case _:
                    result = getattr(platform, arguments.command)(arguments.name)
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, yaml.YAMLError) as exc:
        message = str(exc)
        if arguments.command in {
            "preview",
            "plan",
            "apply",
            "recover-release",
            "receipt",
        } and isinstance(exc, (ValidationError, yaml.YAMLError)):
            message = "invalid deployment configuration"
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1
