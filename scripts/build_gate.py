"""Run release checks and publish a receipt only when every check succeeds."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def fingerprint(root, paths):
    digest = hashlib.sha256()
    files = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file())
    for path in sorted(set(files)):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def run_gate(root, output, commands):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.unlink(missing_ok=True)
    report = root / "results.xml"
    report.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    for command in commands:
        print("BUILD GATE: " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=root, env=environment, check=False)
        if result.returncode:
            raise RuntimeError(f"build check failed with exit {result.returncode}")
    try:
        cases = list(ET.parse(report).getroot().iter("testcase"))
    except (OSError, ET.ParseError) as exc:
        raise RuntimeError("missing or invalid JUnit report") from exc
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skips = Counter(
        case.find("skipped").get("message", "unspecified")
        for case in cases
        if case.find("skipped") is not None
    )
    skipped = sum(skips.values())
    if not cases or failures or errors or len(cases) == skipped:
        raise RuntimeError("JUnit must contain passing tests and no failures or errors")
    receipt = {
        "schema": 1,
        "status": "passed",
        "python": sys.version.split()[0],
        "checks": [{"command": command, "exit_code": 0} for command in commands],
        "pytest": {
            "tests": len(cases),
            "passed": len(cases) - skipped - failures - errors,
            "failures": failures,
            "errors": errors,
            "skipped": skipped,
        },
        "skips": [{"reason": reason, "count": count} for reason, count in sorted(skips.items())],
        "fingerprints": {
            "source": fingerprint(root, [root / "src"]),
            "tests": fingerprint(root, [root / "tests"]),
            "locks": fingerprint(root, list(root.glob("requirements*.lock"))),
            "build": fingerprint(
                root, [root / "scripts", root / "Dockerfile", root / "pyproject.toml"]
            ),
        },
        "tools": {},
    }
    for name in ("pytest", "ruff", "bandit"):
        try:
            receipt["tools"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            receipt["tools"][name] = "unavailable"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("BUILD GATE RECEIPT: " + json.dumps(receipt, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    python = sys.executable
    commands = [
        [python, "-m", "ruff", "check", "src", "tests", "scripts"],
        [python, "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
        [python, "-m", "bandit", "-r", "src", "-q"],
        [python, "-m", "pytest", "-q", "-rs", "--junitxml=results.xml", "-p", "no:cacheprovider"],
    ]
    run_gate(args.root, args.output, commands)


if __name__ == "__main__":
    main()
