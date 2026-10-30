"""Local evaluator: isolated PostgreSQL, captured credentials, real process race.

Run with the repository venv. It reads the existing local Docker PostgreSQL
container, creates only pipefoundry_sentinel_test, and never prints a DSN.
No deployment, remote configuration or sibling repository is modified.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo


def main():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["docker", "inspect", "pipefoundry-postgres-1"],
        capture_output=True,
        text=True,
        check=True,
    )
    settings = dict(
        value.split("=", 1)
        for value in json.loads(result.stdout)[0]["Config"]["Env"]
        if "=" in value
    )
    connection = {
        "host": "127.0.0.1",
        "port": 55435,
        "user": settings.get("POSTGRES_USER", "postgres"),
        "password": settings["POSTGRES_PASSWORD"],
    }
    database = "pipefoundry_sentinel_test"
    assert database.endswith("_test")
    with psycopg.connect(**connection, dbname="postgres", autocommit=True) as db:
        if not db.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database,)).fetchone():
            db.execute(
                "CREATE DATABASE pipefoundry_sentinel_test "
                "TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'"
            )
    environment = os.environ.copy()
    environment.pop("PIPEFOUNDRY_METADATA_DSN", None)
    environment["PIPEFOUNDRY_POSTGRES_DSN"] = make_conninfo(**connection, dbname=database)
    arguments = sys.argv[1:]
    native_image = None
    if arguments[:1] == ["--native-image"]:
        native_image = arguments[1]
        arguments = arguments[2:]
    if native_image:
        # Join only the existing local test server's network namespace. This
        # avoids host-port translation and tests the actual installed ABI.
        environment["PIPEFOUNDRY_POSTGRES_DSN"] = make_conninfo(
            **{**connection, "port": 5432}, dbname=database
        )
        command = [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--network",
            "container:pipefoundry-postgres-1",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m,uid=10001,gid=10001",
            "--env",
            "PIPEFOUNDRY_POSTGRES_DSN",
            native_image,
            "python",
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            "-rs",
            "-p",
            "no:cacheprovider",
            *arguments,
        ]
        filename = "sentinel-native-postgres-tests.txt"
    else:
        command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-rs", *arguments]
        filename = (
            "sentinel-postgres-focused-tests.txt" if arguments else "sentinel-postgres-tests.txt"
        )
    output = root / "evidence" / filename
    run = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True)
    # Successful tests never echo connection settings. Scrub defensively before
    # recording diagnostic evidence from a failed driver/pytest representation.
    text = run.stdout + run.stderr
    for secret in (environment["PIPEFOUNDRY_POSTGRES_DSN"], connection["password"]):
        text = text.replace(secret, "[redacted]")
    output.write_text(text, encoding="utf-8")
    print("\n".join(text.splitlines()[-25:]))
    print("PostgreSQL evaluation exit:", run.returncode)
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
