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


def load(path: str) -> Pipeline:
    source = Path(path)
    if source.stat().st_size > 32768:
        raise ValueError("pipeline config exceeds 32 KiB")
    return Pipeline.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PipeFoundry pipeline lifecycle")
    parser.add_argument(
        "--state-dir", default=os.environ.get("PIPEFOUNDRY_STATE_DIR", ".pipefoundry")
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "render", "deploy", "preview"):
        command = commands.add_parser(name)
        command.add_argument("config")
        if name in {"deploy", "preview"}:
            command.add_argument("--executor", choices=["local", "kubernetes"], default="local")
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
        if arguments.command == "preview" and isinstance(exc, (ValidationError, yaml.YAMLError)):
            message = "invalid deployment configuration"
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1
