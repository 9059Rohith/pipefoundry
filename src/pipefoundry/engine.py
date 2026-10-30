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

import psycopg
import yaml

from pipefoundry.metadata import PostgresConnection
from pipefoundry.models import Pipeline, relative_path, valid_name
from pipefoundry.render import render

MAX_REVISION_ARTIFACTS = 128
MAX_ARTIFACT_BYTES = 131072
METADATA_SCHEMA_LOCK = 1346785350


class Platform:
    def __init__(self, root: str | Path, metadata_dsn: str | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._metadata_dsn = metadata_dsn or os.environ.get("PIPEFOUNDRY_METADATA_DSN")
        self.durable = bool(self._metadata_dsn)
        with self.connect() as db:
            if self.durable:
                # Transaction-scoped locks work with Neon/PgBouncer pooling and
                # serialize fresh-schema creation across simultaneous cold starts.
                db.execute("SELECT pg_advisory_xact_lock(?,1)", (METADATA_SCHEMA_LOCK,))
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
                CREATE TABLE IF NOT EXISTS artifacts (
                  name TEXT NOT NULL, revision INTEGER NOT NULL, path TEXT NOT NULL,
                  contents BLOB NOT NULL CHECK(length(contents)<=131072),
                  PRIMARY KEY(name,revision,path));
                CREATE TABLE IF NOT EXISTS demo_seed (
                  seed_key TEXT PRIMARY KEY, pipeline_name TEXT NOT NULL,
                  owner TEXT NOT NULL, lease_until TEXT NOT NULL,
                  completed INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '');
            """)

    @contextmanager
    def connect(self):
        if self.durable:
            with psycopg.connect(
                self._metadata_dsn, connect_timeout=5, options="-c statement_timeout=10000"
            ) as connection:
                yield PostgresConnection(connection)
            return
        connection = sqlite3.connect(self.root / "metadata.db", timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _store_file(self, db, name: str, revision: int, path: Path, directory: Path):
        relative = path.relative_to(directory).as_posix()
        self._store_bytes(db, name, revision, relative, path.read_bytes())

    def _store_bytes(self, db, name: str, revision: int, relative: str, contents: bytes):
        relative_path(relative)
        if len(contents) > MAX_ARTIFACT_BYTES:
            raise ValueError("revision artifact exceeds 128 KiB")
        budget = db.execute(
            "SELECT COUNT(*),COALESCE(MAX(CASE WHEN path=? THEN 1 ELSE 0 END),0) "
            "FROM artifacts WHERE name=? AND revision=?",
            (relative, name, revision),
        ).fetchone()
        if budget[0] >= MAX_REVISION_ARTIFACTS and not budget[1]:
            raise ValueError("revision artifact limit reached; deploy a new revision")
        db.execute(
            "INSERT INTO artifacts(name,revision,path,contents) VALUES(?,?,?,?) "
            "ON CONFLICT(name,revision,path) DO UPDATE SET contents=excluded.contents",
            (name, revision, relative, contents),
        )

    def _restore_revision(self, name: str, revision: int):
        if not self.durable:
            return
        directory = self.revision_dir(name, revision)
        with self.connect() as db:
            records = list(
                db.execute(
                    "SELECT path,contents FROM artifacts WHERE name=? AND revision=? LIMIT ?",
                    (name, revision, MAX_REVISION_ARTIFACTS + 1),
                )
            )
        if not records:
            raise ValueError("revision artifacts are not committed")
        if len(records) > MAX_REVISION_ARTIFACTS:
            raise ValueError("stored revision artifact limit exceeded")
        # Validate the entire set before writing any bytes into the scratch root.
        checked = []
        for record in records:
            relative = relative_path(record["path"])
            target = (directory / relative).resolve()
            if not target.is_relative_to(directory):
                raise ValueError("stored artifact path escapes revision")
            contents = bytes(record["contents"])
            if len(contents) > MAX_ARTIFACT_BYTES:
                raise ValueError("stored revision artifact exceeds 128 KiB")
            checked.append((target, contents))
        for target, contents in checked:
            if not target.exists() or target.suffix == ".log":
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)

    def _write_log(self, path: Path, text: str):
        text = text.encode("utf-8")[:65536].decode("utf-8", errors="ignore")
        if self.durable:
            relative = path.resolve().relative_to((self.root / "revisions").resolve())
            name, revision = relative.parts[:2]
            valid_name(name)
            directory = self.revision_dir(name, int(revision))
            with self.connect() as db:
                self._store_bytes(
                    db,
                    name,
                    int(revision),
                    path.relative_to(directory).as_posix(),
                    text.encode("utf-8"),
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

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
                if self.durable:
                    for artifact in sorted(directory.rglob("*")):
                        if artifact.is_file():
                            self._store_file(db, config.name, number, artifact, directory)
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

    def _validate_deployment(self, config: Pipeline, executor: str):
        if executor not in {"local", "kubernetes"}:
            raise ValueError("unknown executor")
        if self.durable and executor == "local" and config.output.connector != "postgres":
            raise ValueError("hosted local execution requires PostgreSQL output")

    def preview(self, config: Pipeline, executor: str = "local") -> dict:
        """Compare a metadata snapshot; never restore artifacts or acquire a lease.

        Only typed config/executor participate: operator environment, live resources,
        output data and worker availability are deliberately outside this comparison.
        """
        self._validate_deployment(config, executor)

        def canonical(pipeline, target):
            desired = pipeline.model_dump()
            desired["schedule"] = " ".join(desired["schedule"].split())
            return {"config": desired, "executor": target}

        def fingerprint(value):
            payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()

        def changed_paths(before, after, prefix=""):
            paths = []
            for key in sorted(after):
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(after[key], dict):
                    paths.extend(changed_paths(before[key], after[key], path))
                elif before[key] != after[key]:
                    paths.append({"path": path, "kind": "changed"})
            return paths

        # One statement gives a consistent revision/operation snapshot on both DBs.
        # No status(refresh=True), verified_config or filesystem rehydration here.
        with self.connect() as db:
            row = db.execute(
                "SELECT latest.revision,latest.config,latest.status,latest.executor,"
                "EXISTS(SELECT 1 FROM operations WHERE name=?) AS busy "
                "FROM (SELECT 1) AS anchor LEFT JOIN "
                "(SELECT revision,config,status,executor FROM revisions WHERE name=? "
                "ORDER BY revision DESC LIMIT 1) AS latest ON 1=1",
                (config.name, config.name),
            ).fetchone()
            # The singleton also returns the lease observation before revision 1.
            busy = bool(row["busy"])
        desired = canonical(config, executor)
        current = None
        changes = [{"path": "config", "kind": "added"}, {"path": "executor", "kind": "added"}]
        action = "create"
        if row["revision"] is not None:
            try:
                previous = canonical(Pipeline.model_validate_json(row["config"]), row["executor"])
            except ValueError:
                raise ValueError("stored revision config is invalid") from None
            changes = changed_paths(previous, desired)
            current = {
                "revision": row["revision"],
                "status": row["status"],
                "executor": row["executor"],
                "fingerprint": fingerprint(previous),
            }
            action = (
                "no-op"
                if not changes and not busy and row["status"] in {"succeeded", "deployed"}
                else "update"
            )
        return {
            "name": config.name,
            "action": action,
            "current": current,
            "desired_fingerprint": fingerprint(desired),
            "changes": changes[:12],
            "changes_truncated": len(changes) > 12,
            "operation_in_progress": busy,
            "comparison": "latest recorded revision; no live drift or environment check",
        }

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
                self._write_log(log, f"executor failed: {type(exc).__name__}\n")
                raise RuntimeError("executor unavailable or timed out") from None
            output.seek(0)
            text = output.read(65536).decode("utf-8", errors="replace")
        # Known workers only emit sanitized diagnostics. kubectl diagnostics may
        # include server endpoints, so cluster error output remains operator-only.
        self._write_log(log, text)
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
        self._restore_revision(name, revision)
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
        self._validate_deployment(config, executor)
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
        self._restore_revision(name, status["revision"])
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
