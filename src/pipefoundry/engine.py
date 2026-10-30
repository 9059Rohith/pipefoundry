"""Transactional revisions and lifecycle; external effects never imply success."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3

# Fixed programs and validated argument lists; no user-supplied executable.
import subprocess  # nosec B404
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import yaml

from pipefoundry.models import Pipeline, valid_name
from pipefoundry.render import render


class Platform:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS revisions (
                  name TEXT NOT NULL, revision INTEGER NOT NULL, config TEXT NOT NULL,
                  status TEXT NOT NULL, executor TEXT NOT NULL, created TEXT NOT NULL,
                  checksum TEXT NOT NULL DEFAULT '', PRIMARY KEY(name, revision));
                CREATE TABLE IF NOT EXISTS audit (
                  id INTEGER PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
                  action TEXT NOT NULL, outcome TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                  name TEXT PRIMARY KEY, started TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cluster_targets (
                  name TEXT NOT NULL, namespace TEXT NOT NULL,
                  revision INTEGER NOT NULL, active INTEGER NOT NULL CHECK(active IN (0,1)),
                  PRIMARY KEY(name, namespace));
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.root / "metadata.db", timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def operation(self, name: str):
        valid_name(name)
        with self._lock:
            try:
                with self.connect() as db:
                    db.execute("INSERT INTO operations VALUES (?, ?)", (name, self.now()))
            except sqlite3.IntegrityError:
                raise ValueError(
                    "pipeline has an active operation; inspect operations before retry"
                ) from None
            try:
                yield
            finally:
                with self.connect() as db:
                    db.execute("DELETE FROM operations WHERE name = ?", (name,))

    @staticmethod
    def now():
        return datetime.now(UTC).isoformat()

    def revision_dir(self, name: str, revision: int) -> Path:
        valid_name(name)
        if not isinstance(revision, int) or not 1 <= revision <= 1_000_000:
            raise ValueError("invalid revision")
        base = (self.root / "revisions").resolve()
        target = (base / name / str(revision)).resolve()
        if not base.is_relative_to(self.root) or not target.is_relative_to(base):
            raise ValueError("revision path escapes root")
        return target

    def _new_revision(self, config: Pipeline, executor: str) -> dict:
        if executor not in {"local", "kubernetes", "render"}:
            raise ValueError("unknown executor")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            number = db.execute(
                "SELECT COALESCE(MAX(revision),0)+1 FROM revisions WHERE name=?", (config.name,)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO revisions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    config.name,
                    number,
                    config.model_dump_json(),
                    "rendering",
                    executor,
                    self.now(),
                    "",
                ),
            )
        directory = self.revision_dir(config.name, number)
        try:
            render(config, number, directory)
            checksum = hashlib.sha256((directory / "checksums.json").read_bytes()).hexdigest()
            with self.connect() as db:
                db.execute(
                    "UPDATE revisions SET checksum=?, status='rendered' "
                    "WHERE name=? AND revision=?",
                    (checksum, config.name, number),
                )
        except Exception:
            self._set_status(config.name, number, "failed")
            raise
        return self.status(config.name)

    def render(self, config: Pipeline) -> dict:
        with self.operation(config.name):
            result = self._new_revision(config, "render")
            self._audit(config.name, result["revision"], "render", "succeeded")
            return result

    def _set_status(self, name: str, revision: int, status: str):
        with self.connect() as db:
            db.execute(
                "UPDATE revisions SET status=? WHERE name=? AND revision=?",
                (status, name, revision),
            )

    def _audit(self, name, revision, action, outcome):
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit(name,revision,action,outcome,created) VALUES(?,?,?,?,?)",
                (name, revision, action, outcome, self.now()),
            )

    def _execute(self, args: list[str], log: Path, timeout: int = 180) -> str:
        # Known programs only; file sinks prevent unbounded memory capture.
        with tempfile.TemporaryFile() as output:
            try:
                # No shell; fixed worker module or administrator kubectl executable.
                result = subprocess.run(  # nosec B603
                    args,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                    shell=False,
                )  # noqa: S603
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.write_text(f"executor failed: {type(exc).__name__}\n", encoding="utf-8")
                raise RuntimeError("executor unavailable or timed out") from None
            output.seek(0)
            text = output.read(65536).decode("utf-8", errors="replace")
        # Known workers only emit sanitized diagnostics. kubectl diagnostics may
        # include server endpoints, so cluster error output remains operator-only.
        log.write_text(text, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"executor exited {result.returncode}; inspect pipeline logs")
        return text

    def _kubectl(self) -> str:
        executable = shutil.which("kubectl")
        if not executable:
            raise RuntimeError("kubectl is not available")
        return executable

    def _verified_config(self, name: str, revision: int) -> Pipeline:
        directory = self.revision_dir(name, revision)
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM revisions WHERE name=? AND revision=?", (name, revision)
            ).fetchone()
        if row is None:
            raise ValueError("revision not found")
        payload = (directory / "pipeline.json").read_bytes()
        checksum_bytes = (directory / "checksums.json").read_bytes()
        if hashlib.sha256(checksum_bytes).hexdigest() != row["checksum"]:
            raise ValueError("revision integrity check failed")
        # Also protect the bundle applied to a cluster from local modification.
        checksums = json.loads(checksum_bytes)
        for filename, digest in checksums.items():
            path = (directory / filename).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError("artifact path escapes revision")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("revision artifact integrity check failed")
        return Pipeline.model_validate_json(payload)

    def _run(self, name: str, revision: int, executor: str, partition: str | None = None) -> dict:
        config = self._verified_config(name, revision)
        directory = self.revision_dir(name, revision)
        log = directory / f"run-{partition or 'latest'}.log"
        if executor == "local":
            args = [
                sys.executable,
                "-m",
                "pipefoundry.worker",
                "--config",
                str(directory / "pipeline.json"),
                "--root",
                str(self.root),
            ]
            if partition:
                args += ["--partition", partition]
            return json.loads(self._execute(args, log, 300))
        if executor == "kubernetes":
            kubectl = self._kubectl()
            namespace = valid_name(os.environ.get("PIPEFOUNDRY_NAMESPACE", "pipefoundry"))
            # Persist intent before apply: even a failed multi-object operation
            # can leave resources, and later renders/local runs cannot erase it.
            with self.connect() as db:
                db.execute(
                    "INSERT INTO cluster_targets VALUES (?,?,?,1) "
                    "ON CONFLICT(name,namespace) DO UPDATE SET revision=excluded.revision,active=1",
                    (name, namespace, revision),
                )
            if partition:
                objects = list(yaml.safe_load_all((directory / "bundle.yaml").read_text()))
                spec = objects[1]["spec"]["jobTemplate"]["spec"]
                spec["template"]["spec"]["containers"][0]["args"] += ["--partition", partition]
                jobname = f"{name}-bf-{partition.replace('-', '')}-r{revision}"
                manifest = {
                    "apiVersion": "batch/v1",
                    "kind": "Job",
                    "metadata": {"name": jobname, "labels": {"pipeline": name}},
                    "spec": spec,
                }
                jobfile = directory / f"backfill-{partition}.yaml"
                jobfile.write_text(yaml.safe_dump(manifest), encoding="utf-8")
                self._execute([kubectl, "-n", namespace, "apply", "-f", str(jobfile)], log, 30)
                self._execute(
                    [
                        kubectl,
                        "-n",
                        namespace,
                        "wait",
                        "--for=condition=complete",
                        f"job/{jobname}",
                        "--timeout=300s",
                    ],
                    log,
                    310,
                )
                return {"job": jobname, "status": "completed"}
            self._execute(
                [kubectl, "-n", namespace, "apply", "-f", str(directory / "bundle.yaml")], log, 30
            )
            self._execute(
                [kubectl, "-n", namespace, "get", "cronjob", config.name, "-o", "json"], log, 30
            )
            return {"status": "deployed", "meaning": "API server accepted CronJob; no run implied"}
        raise ValueError("pipeline is not deployed")

    def deploy(self, config: Pipeline, executor: str = "local", action: str = "deploy") -> dict:
        with self.operation(config.name):
            result = self._new_revision(config, executor)
            revision = result["revision"]
            self._set_status(
                config.name, revision, "running" if executor == "local" else "deploying"
            )
            try:
                self._run(config.name, revision, executor)
            except Exception:
                self._set_status(config.name, revision, "failed")
                self._audit(config.name, revision, action, "failed")
                raise
            self._set_status(
                config.name, revision, "succeeded" if executor == "local" else "deployed"
            )
            self._audit(config.name, revision, action, "succeeded")
            return self.status(config.name)

    def list(self) -> list[dict]:
        with self.connect() as db:
            names = [
                row[0] for row in db.execute("SELECT DISTINCT name FROM revisions ORDER BY name")
            ]
        return [self.status(name) for name in names]

    def status(self, name: str, refresh: bool = False) -> dict:
        valid_name(name)
        with self.connect() as db:
            row = db.execute(
                "SELECT name,revision,status,executor,created FROM revisions "
                "WHERE name=? ORDER BY revision DESC LIMIT 1",
                (name,),
            ).fetchone()
            targets = [
                dict(target)
                for target in db.execute(
                    "SELECT namespace,revision AS last_attempted_revision FROM cluster_targets "
                    "WHERE name=? AND active=1 ORDER BY namespace",
                    (name,),
                )
            ]
        if row is None:
            raise ValueError("pipeline not found")
        result = dict(row)
        result["cluster_targets"] = targets
        observations = {}
        for target in targets if refresh else []:
            namespace = valid_name(target["namespace"])
            output = self._execute(
                [self._kubectl(), "-n", namespace, "get", "cronjob", name, "-o", "json"],
                self.revision_dir(name, result["revision"]) / f"status-{namespace}.log",
                30,
            )
            live = json.loads(output)
            observed = live.get("status", {})
            observations[namespace] = {
                "last_schedule_time": observed.get("lastScheduleTime"),
                "last_successful_time": observed.get("lastSuccessfulTime"),
                "active_jobs": len(observed.get("active", [])),
                "suspended": live.get("spec", {}).get("suspend", False),
            }
        if observations:
            result["clusters"] = observations
            if len(observations) == 1:
                result["cluster"] = next(iter(observations.values()))
        return result

    def config(self, name: str) -> Pipeline:
        return self._verified_config(name, self.status(name)["revision"])

    def logs(self, name: str) -> list[str]:
        status = self.status(name)
        directory = self.revision_dir(name, status["revision"])
        logs = []
        for target in status["cluster_targets"]:
            namespace = valid_name(target["namespace"])
            output = self._execute(
                [
                    self._kubectl(),
                    "-n",
                    namespace,
                    "logs",
                    "-l",
                    f"pipeline={name}",
                    "--all-containers=true",
                    "--tail=200",
                    "--limit-bytes=65536",
                    "--prefix=true",
                    "--max-log-requests=5",
                ],
                directory / f"cluster-{namespace}.log",
                30,
            )
            logs.append(output)
        if status["executor"] == "local":
            logs.extend(
                path.read_text(encoding="utf-8")[:65536]
                for path in sorted(directory.glob("run-*.log"))[-32:]
            )
        return logs

    def audit(self, name: str) -> list[dict]:
        valid_name(name)
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM audit WHERE name=? ORDER BY id LIMIT 1000", (name,)
                )
            ]

    def backfill(self, name: str, start: str, end: str) -> dict:
        begin, finish = date.fromisoformat(start), date.fromisoformat(end)
        days = (finish - begin).days + 1
        if not 1 <= days <= 31:
            raise ValueError("backfill must span 1 to 31 inclusive UTC dates")
        with self.operation(name):
            current = self.status(name)
            if current["status"] not in {"succeeded", "deployed"}:
                raise ValueError("pipeline is not deployed")
            try:
                for offset in range(days):
                    partition = (begin + timedelta(days=offset)).isoformat()
                    self._run(name, current["revision"], current["executor"], partition)
            except Exception:
                self._audit(name, current["revision"], "backfill", "failed")
                raise
            self._audit(name, current["revision"], "backfill", "succeeded")
            return {"name": name, "partitions": days, "start": start, "end": end}

    def rollback(self, name: str, revision: int) -> dict:
        current = self.status(name)
        config = self._verified_config(name, revision)
        if current["executor"] == "render":
            raise ValueError("pipeline is not deployed")
        return self.deploy(config, current["executor"], action="rollback")

    def teardown(self, name: str) -> dict:
        with self.operation(name):
            current = self.status(name)
            for target in current["cluster_targets"]:
                namespace = valid_name(target["namespace"])
                log = self.revision_dir(name, current["revision"]) / f"teardown-{namespace}.log"
                try:
                    self._execute(
                        [
                            self._kubectl(),
                            "-n",
                            namespace,
                            "delete",
                            "cronjob,job,configmap",
                            "-l",
                            f"pipeline={name}",
                            "--ignore-not-found=true",
                        ],
                        log,
                        60,
                    )
                except Exception:
                    self._audit(name, current["revision"], "teardown", "failed")
                    raise
                with self.connect() as db:
                    db.execute(
                        "UPDATE cluster_targets SET active=0 WHERE name=? AND namespace=?",
                        (name, namespace),
                    )
            self._set_status(name, current["revision"], "torn_down")
            self._audit(name, current["revision"], "teardown", "succeeded")
            return self.status(name)
