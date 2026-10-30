# Release Sentinel Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, with test-driven-development and verification-before-completion. The user explicitly requested autonomous execution without questions.

**Goal:** Make reviewed releases executable with durable identity, bounded risk and race-resistant idempotency.

**Architecture:** Store canonical immutable plans in metadata, binding desired configuration, exact recorded state, artifacts, package source, operator settings and policy. Apply obtains the existing pipeline lease, validates the stored plan, reserves a receipt and revision in one short transaction, then renders and runs without a transaction or nested lease. Retries return the durable receipt; failures require a new reviewed plan, while interrupted attempts have explicit operator-confirmed recovery.

**Tech Stack:** Existing Python, Pydantic, FastAPI, SQLite/PostgreSQL, pytest and Docker; no dependency upgrades.

**Spec:** Parent task's Release Sentinel requirements, preserved in the architecture and constraints below.

## Global Constraints

- Work only in PipeFoundry; no deploy/push or workflow changes; preserve legacy lifecycle entrypoints.
- Never include operator secrets in plans/errors. Store a private random HMAC key in metadata for environment drift detection.
- Acquire durable lease before optimistic state check; reserve receipt/revision atomically; never hold a DB transaction across execution.
- Plan ID/digest identifies immutable server-owned content. Caller cannot submit executable plan contents.
- Strict operation, CPU, memory, conservative input-row and expiry budgets. Release runs one current partition, never a backfill.
- Crash/ambiguous outcomes never automatically rerun. Recovery requires trusted operator confirmation that the worker/controller has stopped.
- Honest cluster semantics: accepted CronJob is not proof of a completed workload; pin image digest for guarded Kubernetes releases.

## Review Focus

- A legacy deploy changes state between plan/apply: exact revision/status/artifact state rejects the old plan.
- An unchanged config runs different worker/template/environment: code, generated artifact and operator identities reject drift.
- Process dies after reserving work: receipt survives, retry cannot launch work, explicit recovery closes ambiguity.
- Independent processes race: lease + atomic receipt reservation permits one revision and worker only.
- Malformed/secret-bearing API/CLI inputs: bounded typed input produces sanitized diagnostics.

### Task 1: Immutable plans and policy

**Files:** Create `src/pipefoundry/releases.py`, `src/pipefoundry/release_models.py`, `tests/test_releases.py`; modify metadata bootstrap/prefix table list.
**Interfaces:** `ReleaseSentinel(platform).plan(config, executor='local', policy=RolloutPolicy(), ttl_seconds=300) -> dict` and `get_plan(plan_id, digest) -> dict`.

- [x] Write and run failing tests for canonical server-owned plan, budgets, expiry, code/operator/artifact drift and tampered stored plan.
- [x] Implement typed policy, canonical digest, snapshot, source/artifact/operator identity and immutable durable plan storage.
- [x] Run release unit tests; verify policy errors do not leak secrets.

### Task 2: Leased apply, receipts and recovery

**Files:** Modify `src/pipefoundry/engine.py`, `src/pipefoundry/releases.py`, `tests/test_releases.py`; create `tests/test_release_races.py`.
**Interfaces:** `apply(plan_id, digest, idempotency_key) -> dict`, `receipt(idempotency_key) -> dict`, `recover(idempotency_key, confirm_worker_stopped=True) -> dict`.

- [x] Write and run failing tests for stale state, idempotency, failed worker, interrupted receipt and independent process race.
- [x] Split reserve/materialize in engine, bind lease cleanup to owner timestamp, atomically reserve release receipt and revision, execute under lease, persist terminal outcome.
- [x] Add explicit interrupted-receipt recovery without worker relaunch; test real PostgreSQL cold roots and races.

### Task 3: Protected interfaces and operational evidence

**Files:** Modify API/CLI/README; add interface tests and `scripts/verify_sentinel.py`.
**Interfaces:** authenticated `POST /releases/plan`, `POST /releases/apply`, `GET /releases/receipts/{key}`, `POST /releases/recover`; CLI `plan`, `apply`, `receipt`, `recover-release`.

- [x] Write and run failing API/CLI authentication, validation, sanitized error and real successful apply tests.
- [x] Implement interfaces, docs, threat model/recovery and reproducible local PostgreSQL/image evaluation.
- [x] Run full suite, lint/security checks and PostgreSQL suite; build `pipefoundry:sentinel`, exercise native image HTTP, record evidence and executable production/test LOC separately.
- [x] Review final diff, commit on existing main, report evidence and limitations without deployment claims.
