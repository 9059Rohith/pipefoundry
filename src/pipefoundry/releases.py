"""Release Sentinel: durable reviewed intent and at-most-once launch reservations.

The metadata database and trusted operator are the authority. Plan files are
review copies, never executable instructions. A process interruption is an
ambiguous outcome, never permission to repeat an external effect.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.metadata
import json
import os
import re
import secrets
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from pipefoundry.models import Pipeline, relative_path
from pipefoundry.release_models import ApplyRequest, PlanReference, RolloutPolicy
from pipefoundry.render import render
from pipefoundry.workloads import FIXTURE, MAX_ROWS

MAX_PLAN_BYTES = 16384
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
PINNED_IMAGE = re.compile(r"^[A-Za-z0-9._:/-]+@sha256:[0-9a-f]{64}$")
OPERATOR_KEYS = (
    "PIPEFOUNDRY_WORKER_IMAGE",
    "PIPEFOUNDRY_NAMESPACE",
    "PIPEFOUNDRY_POSTGRES_DSN",
    "PIPEFOUNDRY_ORDERS_URL",
    "PIPEFOUNDRY_ALLOWED_HOSTS",
    "PIPEFOUNDRY_CA_BUNDLE",
    "KUBECONFIG",
    "PATH",
    "PYTHONPATH",
    "JAVA_HOME",
    "SPARK_HOME",
    "PYSPARK_PYTHON",
    "PYSPARK_DRIVER_PYTHON",
    "JAVA_TOOL_OPTIONS",
    "PYSPARK_SUBMIT_ARGS",
    "SPARK_CONF_DIR",
    "SPARK_LOCAL_DIRS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


def canonical(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value: dict) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def canonical_config(config: Pipeline) -> Pipeline:
    data = config.model_dump()
    data["schedule"] = " ".join(data["schedule"].split())
    return Pipeline.model_validate(data)


class ReleaseSentinel:
    def __init__(self, platform):
        self.platform = platform
        # ON CONFLICT allows simultaneous cold roots to converge on one authority.
        with platform.connect() as db:
            db.execute(
                "INSERT INTO release_settings(setting,value) VALUES('hmac-key',?) "
                "ON CONFLICT(setting) DO NOTHING",
                (secrets.token_hex(32),),
            )
            self._key = bytes.fromhex(
                db.execute(
                    "SELECT value FROM release_settings WHERE setting='hmac-key'"
                ).fetchone()[0]
            )

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    def _mac(self, value: str) -> str:
        return hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()

    def _operator_identity(self) -> str:
        values = {key: os.environ.get(key, "") for key in OPERATOR_KEYS}
        # libpq accepts connection behavior and credential defaults independently
        # of the configured DSN. Fingerprint them without exposing their values.
        values.update({key: value for key, value in os.environ.items() if key.startswith("PG")})
        # File-backed operator credentials/CA material must drift with contents,
        # not just a stable filename. Nothing from these files leaves the MAC.
        for key in ("PIPEFOUNDRY_CA_BUNDLE", "KUBECONFIG"):
            if values[key]:
                paths = values[key].split(os.pathsep) if key == "KUBECONFIG" else [values[key]]
                files = []
                for filename in paths[:8]:
                    try:
                        path = Path(filename)
                        if path.stat().st_size > 1_048_576:
                            raise ValueError("operator file exceeds identity size limit")
                        files.append(hashlib.sha256(path.read_bytes()).hexdigest())
                    except OSError:
                        raise ValueError("operator identity file is unavailable") from None
                values[key + "_contents"] = files
        # Default kubectl configuration is operator state too.
        if not values["KUBECONFIG"]:
            default = Path.home() / ".kube" / "config"
            if default.exists():
                if default.stat().st_size > 1_048_576:
                    raise ValueError("operator file exceeds identity size limit")
                values["default_kubeconfig"] = hashlib.sha256(default.read_bytes()).hexdigest()
        return self._mac(canonical(values))

    @staticmethod
    def _code_identity() -> str:
        package = Path(__file__).parent
        sources = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(package.glob("*.py"))
        }
        versions = {}
        for name in ("fastapi", "pydantic", "PyYAML", "croniter", "httpx", "psycopg"):
            versions[name] = importlib.metadata.version(name)
        return digest({"sources": sources, "dependencies": versions, "python": sys.version})

    def _artifact_identity(self, db, row) -> str:
        if self.platform.durable:
            records = list(
                db.execute(
                    "SELECT path,contents FROM artifacts WHERE name=? AND revision=? ORDER BY path",
                    (row["name"], row["revision"]),
                )
            )
            if len(records) > 128:
                raise ValueError("current artifacts are invalid")
            contents = {
                relative_path(record["path"]): bytes(record["contents"])
                for record in records
                if not record["path"].endswith(".log")
            }
        else:
            directory = self.platform.revision_dir(row["name"], row["revision"])
            paths = sorted(directory.rglob("*"))
            if len(paths) > 256:
                raise ValueError("current artifacts are invalid")
            contents = {}
            for path in paths:
                if path.is_file() and path.suffix != ".log":
                    if not path.resolve().is_relative_to(directory.resolve()):
                        raise ValueError("current artifacts are invalid")
                    if path.stat().st_size > 131072:
                        raise ValueError("current artifacts are invalid")
                    contents[path.relative_to(directory).as_posix()] = path.read_bytes()
        if any(len(payload) > 131072 for payload in contents.values()):
            raise ValueError("current artifacts are invalid")
        # Failed/incomplete revisions may contain partial files. Bind all bytes
        # as the optimistic precondition, but never treat them as runnable or
        # eligible for no-op. Recovery must be able to replace a partial render.
        if row["status"] not in {"succeeded", "deployed"}:
            return digest(
                {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
            )
        # A corrupted current revision is not a successful no-op candidate.
        try:
            manifest = contents["checksums.json"]
            if hashlib.sha256(manifest).hexdigest() != row["checksum"]:
                raise ValueError
            checksums = json.loads(manifest)
            for name, expected in checksums.items():
                relative_path(name)
                if hashlib.sha256(contents[name]).hexdigest() != expected:
                    raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("current artifacts are invalid") from None
        return digest({name: hashlib.sha256(data).hexdigest() for name, data in contents.items()})

    def _snapshot(self, db, name: str) -> dict | None:
        row = db.execute(
            "SELECT * FROM revisions WHERE name=? ORDER BY revision DESC LIMIT 1", (name,)
        ).fetchone()
        if row is None:
            return None
        try:
            config = canonical_config(Pipeline.model_validate_json(row["config"]))
        except ValueError:
            raise ValueError("stored revision config is invalid") from None
        identity = db.execute(
            "SELECT code_identity,operator_identity,artifact_identity "
            "FROM revision_identities WHERE name=? AND revision=?",
            (name, row["revision"]),
        ).fetchone()
        return {
            "revision": row["revision"],
            "status": row["status"],
            "executor": row["executor"],
            "created": row["created"],
            "config_fingerprint": digest(
                {"config": config.model_dump(), "executor": row["executor"]}
            ),
            "checksum": row["checksum"],
            "artifacts": self._artifact_identity(db, row),
            "runtime_identity": dict(identity) if identity else None,
        }

    def _desired_artifacts(self, config: Pipeline, revision: int) -> str:
        with tempfile.TemporaryDirectory(prefix="pipefoundry-plan-") as scratch:
            directory = Path(scratch) / "artifacts"
            checksums = render(config, revision, directory)
            return digest(checksums)

    @staticmethod
    def _risks(config: Pipeline, executor: str, operation: str) -> dict:
        rows = len(FIXTURE) if config.input.connector == "fixture" else MAX_ROWS
        reasons = [f"{operation}: latest recorded state is the optimistic precondition"]
        if operation == "no-op":
            reasons.append("No worker or new revision is launched")
        else:
            reasons.append("One current UTC partition may be written; existing IDs may be updated")
        reasons.append(
            "Fixture has 3 input rows"
            if config.input.connector == "fixture"
            else "Input is not sampled: conservative worker upper bound is 10000 rows"
        )
        if executor == "kubernetes":
            reasons.append(
                "Cluster admission is not workload completion; live cluster drift is not inspected"
            )
        else:
            reasons.append(
                "CPU/memory budgets cover declared requests; local OS limits are operator-managed"
            )
        return {
            "input_rows_upper_bound": rows,
            "backfill_partitions": 0,
            "cpu_millis": config.resources.cpu_millis,
            "memory_mib": config.resources.memory_mib,
            "reasons": reasons,
        }

    @staticmethod
    def _enforce(policy: RolloutPolicy, risk: dict, operation: str):
        if policy.allowed_operation is not None and policy.allowed_operation != operation:
            raise ValueError("rollout policy denies operation")
        for actual, limit in (
            ("cpu_millis", "max_cpu_millis"),
            ("memory_mib", "max_memory_mib"),
            ("input_rows_upper_bound", "max_input_rows"),
        ):
            if risk[actual] > getattr(policy, limit):
                raise ValueError("rollout policy budget exceeded: " + limit)

    def plan(
        self,
        config: Pipeline,
        executor: str = "local",
        *,
        policy: RolloutPolicy | None = None,
        ttl_seconds: int = 300,
    ) -> dict:
        config = canonical_config(Pipeline.model_validate(config))
        self.platform._validate_deployment(config, executor)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("plan expiry must be 1 to 3600 seconds")
        if executor == "kubernetes" and not PINNED_IMAGE.fullmatch(
            os.environ.get("PIPEFOUNDRY_WORKER_IMAGE", "")
        ):
            raise ValueError("guarded Kubernetes releases require a digest-pinned worker image")
        policy = RolloutPolicy.model_validate(policy or RolloutPolicy())
        with self.platform.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM operations WHERE name=?", (config.name,)).fetchone():
                raise ValueError("pipeline has an active operation; plan after it completes")
            expected = self._snapshot(db, config.name)
        desired = digest({"config": config.model_dump(), "executor": executor})
        code_identity = self._code_identity()
        operator_identity = self._operator_identity()
        operation = "create" if expected is None else "update"
        if (
            expected
            and expected["config_fingerprint"] == desired
            and expected["status"] in {"succeeded", "deployed"}
            and expected["runtime_identity"]
            == {
                "code_identity": code_identity,
                "operator_identity": operator_identity,
                "artifact_identity": self._desired_artifacts(config, expected["revision"]),
            }
        ):
            operation = "no-op"
        # Persist the resolved operation, even when the caller accepts the inferred one.
        policy = policy.model_copy(
            update={"allowed_operation": policy.allowed_operation or operation}
        )
        risk = self._risks(config, executor, operation)
        self._enforce(policy, risk, operation)
        revision = 1 if expected is None else expected["revision"] + (operation != "no-op")
        now = self.now()
        payload = {
            "schema_version": 1,
            "plan_id": secrets.token_hex(16),
            "name": config.name,
            "created": now.isoformat(),
            "expires": (now + timedelta(seconds=ttl_seconds)).isoformat(),
            "config": config.model_dump(),
            "executor": executor,
            "operation": operation,
            "desired_fingerprint": desired,
            "expected": expected,
            "code_identity": code_identity,
            "operator_identity": operator_identity,
            "artifact_identity": self._desired_artifacts(config, revision),
            "revision": revision,
            "policy": policy.model_dump(),
            "risk": risk,
        }
        encoded = canonical(payload)
        if len(encoded.encode()) > MAX_PLAN_BYTES:
            raise ValueError("release plan exceeds size limit")
        identity = digest(payload)
        with self.platform.connect() as db:
            db.execute(
                "INSERT INTO release_plans VALUES(?,?,?,?,?,?)",
                (
                    payload["plan_id"],
                    config.name,
                    identity,
                    encoded,
                    self._mac(encoded),
                    now.isoformat(),
                ),
            )
        return {**payload, "digest": identity}

    def get_plan(self, plan_id: str, plan_digest: str) -> dict:
        try:
            PlanReference(plan_id=plan_id, digest=plan_digest)
        except ValidationError:
            raise ValueError("invalid plan identity") from None
        with self.platform.connect() as db:
            row = db.execute("SELECT * FROM release_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None or not secrets.compare_digest(row["digest"], plan_digest):
            raise ValueError("release plan identity not found")
        try:
            if len(row["payload"].encode()) > MAX_PLAN_BYTES:
                raise ValueError
            payload = json.loads(row["payload"])
            if (
                payload["plan_id"] != plan_id
                or payload["name"] != row["name"]
                or digest(payload) != plan_digest
                or not secrets.compare_digest(self._mac(row["payload"]), row["authentication"])
            ):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise ValueError("release plan integrity check failed") from None
        return {**payload, "digest": plan_digest}

    def _validate_execution(self, plan: dict, db):
        if self.now() >= datetime.fromisoformat(plan["expires"]):
            raise ValueError("release plan expired; create a new plan")
        if plan["code_identity"] != self._code_identity():
            raise ValueError("release code changed; create a new plan")
        if plan["operator_identity"] != self._operator_identity():
            raise ValueError("operator settings changed; create a new plan")
        try:
            current = self._snapshot(db, plan["name"])
        except ValueError:
            raise ValueError("release plan stale: current artifacts or config changed") from None
        if current != plan["expected"]:
            raise ValueError("release plan stale: latest recorded state changed")
        config = Pipeline.model_validate(plan["config"])
        self.platform._validate_deployment(config, plan["executor"])
        if self._desired_artifacts(config, plan["revision"]) != plan["artifact_identity"]:
            raise ValueError("release template artifacts changed; create a new plan")
        self._enforce(
            RolloutPolicy.model_validate(plan["policy"]),
            self._risks(config, plan["executor"], plan["operation"]),
            plan["operation"],
        )

    @staticmethod
    def _key_valid(key: str):
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid idempotency key")

    @staticmethod
    def _receipt(row) -> dict:
        return {
            key: row[key]
            for key in (
                "idempotency_key",
                "plan_id",
                "digest",
                "name",
                "revision",
                "operation",
                "state",
                "created",
                "updated",
                "error_code",
            )
        }

    def receipt(self, idempotency_key: str) -> dict:
        self._key_valid(idempotency_key)
        with self.platform.connect() as db:
            row = db.execute(
                "SELECT * FROM release_receipts WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
        if row is None:
            raise ValueError("release receipt not found")
        return self._receipt(row)

    def _existing(self, db, key: str, plan: dict) -> dict | None:
        row = db.execute(
            "SELECT * FROM release_receipts WHERE idempotency_key=?", (key,)
        ).fetchone()
        if row:
            if row["plan_id"] != plan["plan_id"] or row["digest"] != plan["digest"]:
                raise ValueError("idempotency key is bound to another plan")
            return self._receipt(row)
        if db.execute(
            "SELECT 1 FROM release_receipts WHERE plan_id=?", (plan["plan_id"],)
        ).fetchone():
            raise ValueError("release plan already applied; use its original idempotency key")
        return None

    def apply(self, plan_id: str, plan_digest: str, idempotency_key: str) -> dict:
        try:
            ApplyRequest(plan_id=plan_id, digest=plan_digest, idempotency_key=idempotency_key)
        except ValidationError:
            raise ValueError("invalid release apply request") from None
        plan = self.get_plan(plan_id, plan_digest)
        # Retry is an observation, including expired plans and interrupted receipts.
        with self.platform.connect() as db:
            existing = self._existing(db, idempotency_key, plan)
        if existing is not None:
            return existing
        try:
            with self.platform.operation(plan["name"]) as owner:
                return self._apply_under_lease(plan, idempotency_key, owner)
        except sqlite3.IntegrityError:
            # Different pipeline names may race on the same global idempotency key.
            raise ValueError("idempotency reservation conflict; inspect receipt") from None

    def _apply_under_lease(self, plan: dict, key: str, owner: str) -> dict:
        now = self.now().isoformat()
        with self.platform.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = self._existing(db, key, plan)
            if existing is not None:
                return existing
            self._validate_execution(plan, db)
            # Reservation and receipt are committed together before any external effect.
            db.execute(
                "INSERT INTO release_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    plan["plan_id"],
                    plan["digest"],
                    plan["name"],
                    plan["revision"],
                    plan["operation"],
                    "succeeded" if plan["operation"] == "no-op" else "executing",
                    owner,
                    now,
                    now,
                    "",
                ),
            )
            if plan["operation"] != "no-op":
                db.execute(
                    "INSERT INTO revisions VALUES(?,?,?,'rendering',?,?, '')",
                    (
                        plan["name"],
                        plan["revision"],
                        canonical(plan["config"]),
                        plan["executor"],
                        now,
                    ),
                )
        if plan["operation"] == "no-op":
            return self.receipt(key)
        self._execute_reserved(plan, key)
        return self.receipt(key)

    def _execute_reserved(self, plan: dict, key: str):
        name, revision, executor = plan["name"], plan["revision"], plan["executor"]
        try:
            self.platform._materialize_revision(
                Pipeline.model_validate(plan["config"]), executor, revision
            )
            directory = self.platform.revision_dir(name, revision)
            actual = digest(json.loads((directory / "checksums.json").read_text(encoding="utf-8")))
            if actual != plan["artifact_identity"]:
                raise ValueError("materialized release artifacts differ from the plan")
            self.platform._set_status(
                name, revision, "running" if executor == "local" else "deploying"
            )
            self.platform._run(name, revision, executor)
        except Exception:
            # Do not reflect connector, DB or operator exception details into receipts.
            self._finish(key, name, revision, "failed", "execution_failed")
            return
        self._finish(key, name, revision, "succeeded", "")

    def _finish(self, key: str, name: str, revision: int, state: str, error: str):
        with self.platform.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE release_receipts SET updated=updated WHERE idempotency_key=?", (key,)
            )
            # Status, receipt and audit are one atomic durable outcome.
            row = db.execute(
                "SELECT * FROM release_receipts WHERE idempotency_key=?", (key,)
            ).fetchone()
            if row["state"] != "executing":
                raise ValueError(
                    "release receipt was recovered; execution outcome requires inspection"
                )
            status = state
            if state == "succeeded":
                executor = db.execute(
                    "SELECT executor FROM revisions WHERE name=? AND revision=?", (name, revision)
                ).fetchone()[0]
                status = "succeeded" if executor == "local" else "deployed"
            db.execute(
                "UPDATE revisions SET status=? WHERE name=? AND revision=?",
                (status, name, revision),
            )
            db.execute(
                "UPDATE release_receipts SET state=?,updated=?,error_code=? "
                "WHERE idempotency_key=?",
                (state, self.now().isoformat(), error, key),
            )
            db.execute(
                "INSERT INTO audit(name,revision,action,outcome,created) VALUES(?,?,'release',?,?)",
                (name, revision, state, self.now().isoformat()),
            )

    def recover(self, idempotency_key: str, *, confirm_worker_stopped: bool) -> dict:
        self._key_valid(idempotency_key)
        if confirm_worker_stopped is not True:
            raise ValueError(
                "recovery requires operator confirmation that controller and worker stopped"
            )
        with self.platform.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM release_receipts WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if row is None:
                raise ValueError("release receipt not found")
            if row["state"] == "executing":
                # On PG serialize recovery versus terminal outcome and other recoveries.
                db.execute(
                    "UPDATE release_receipts SET updated=updated WHERE idempotency_key=?",
                    (idempotency_key,),
                )
                row = db.execute(
                    "SELECT * FROM release_receipts WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if row["state"] != "executing":
                    return self._receipt(row)
                active = db.execute(
                    "SELECT started FROM operations WHERE name=?", (row["name"],)
                ).fetchone()
                if active and active[0] != row["lease_owner"]:
                    raise ValueError("a different pipeline operation is active")
                db.execute(
                    "UPDATE release_receipts SET state='failed',error_code='interrupted',updated=? "
                    "WHERE idempotency_key=?",
                    (self.now().isoformat(), idempotency_key),
                )
                db.execute(
                    "UPDATE revisions SET status='failed' WHERE name=? AND revision=?",
                    (row["name"], row["revision"]),
                )
                db.execute(
                    "DELETE FROM operations WHERE name=? AND started=?",
                    (row["name"], row["lease_owner"]),
                )
                db.execute(
                    "INSERT INTO audit(name,revision,action,outcome,created) "
                    "VALUES(?,?,'release-recovery','interrupted',?)",
                    (row["name"], row["revision"], self.now().isoformat()),
                )
        return self.receipt(idempotency_key)
