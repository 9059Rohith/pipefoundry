# Release Sentinel

Sentinel turns a review into durable, bounded execution authority. The earlier `preview` remains a read-only advisory comparison. Legacy deploy/render/backfill/rollback/teardown retain their interfaces and share the same pipeline operation row with Sentinel.

## Review and apply

```json
{
  "config": {"name": "orders-release", "schedule": "0 * * * *"},
  "executor": "local",
  "ttl_seconds": 300,
  "policy": {
    "allowed_operation": "create",
    "max_cpu_millis": 250,
    "max_memory_mib": 256,
    "max_input_rows": 3
  }
}
```

Send this to authenticated `POST /releases/plan`. The response contains `plan_id`, `digest`, canonical configuration, exact expected state, resolved operation, expiry, risk reasons and identity digests. CPU bounds are 50–4000 millicores, memory 64–8192 MiB, rows 1–10000, and TTL 1–3600 seconds; booleans are not integers. All request models forbid unknown fields. Omitting `allowed_operation` accepts the operation inferred at plan time and freezes that value. Specifying it rejects an unexpected create/update/no-op before a plan is stored.

Apply only the returned identity:

```json
{"plan_id":"<32 lowercase hex>","digest":"<64 lowercase hex>","idempotency_key":"orders-release-20261030"}
```

`POST /releases/apply` returns a durable receipt. Inspect `state`, rather than treating HTTP 200 as successful execution: a failed worker yields a terminal `failed` receipt with a bounded `execution_failed` code. An interrupted controller may leave `executing`. The receipt route never launches work. Invalid/stale/expired requests fail before reservation. Normal token authentication and 32 KiB body limits apply to all routes; invalid release payloads return sanitized 422 errors without reflecting pasted credentials.

The CLI saves a review copy with `plan CONFIG > release.json`, applies with `apply release.json --idempotency-key KEY`, and observes with `receipt KEY`. The CLI checks the digest of the entire review file, then the server-owned record. A caller cannot execute edited fields by recomputing the review-file digest: the immutable server record and its authentication still have to match. Keys contain 8–80 ASCII letters, digits, underscores or hyphens. A key cannot bind another plan; a plan cannot reserve work under another key.

## What the plan binds

| Identity | Meaning |
|---|---|
| Canonical config/executor | Typed config with normalized schedule whitespace; semantic cron equivalence is not inferred |
| Expected latest state | Revision, exact status, creation time, config/executor digest, committed checksum and immutable artifact bytes |
| Runtime identity | SHA-256 of installed package Python sources, relevant dependency versions and Python version |
| Operator identity | HMAC over selected worker/connector/cluster settings and configured CA/kubeconfig contents; raw settings and credentials never appear in the plan |
| Desired artifact identity | Actual rendered manifest checksum map for the reserved revision, verified again before launch |
| Policy and expiry | Resolved allowed operation, declared CPU/memory ceilings, conservative per-run input-row ceiling and expiry |

Per-revision runtime identities are committed during materialization, including through legacy lifecycle commands. A no-op is possible only when config, successful recorded state, code, operator settings and generated artifacts agree. Revisions predating this feature lack runtime identity and produce an update. Extra immutable revision files participate in the optimistic snapshot; mutable logs do not invalidate a plan.

Fixture input has three rows. Dynamic API/Spark inputs are not fetched or sampled during planning: their upper bound is the existing worker limit of 10,000 rows. A lower policy rejects those sources conservatively. Sentinel executes one current UTC partition and cannot request backfill. It does not reserve existing output rows or compare external source contents. Declared local CPU/memory requests are a review budget, not OS resource enforcement. Kubernetes manifests enforce their declared limits but require a real cluster to exercise them.

## Race and transaction invariants

1. Acquire the durable per-pipeline `operations` row, also used by legacy writers.
2. Begin a short transaction; recheck idempotency and the full plan against current state.
3. Insert receipt and reserved revision atomically, then commit.
4. Render and execute while retaining the operation row; no database transaction is held across subprocess or network execution.
5. Commit revision status, receipt outcome and audit event together; release only the lease owned by this attempt.

Different pipeline releases can progress concurrently. Different processes applying the same plan cannot reserve another revision. An idempotent retry may observe `executing` immediately; it does not wait for or relaunch the original worker. Terminal receipts remain usable after expiry. Expiry governs new reservations, not an already accepted worker's execution deadline.

SQLite uses WAL and immediate reservation transactions. PostgreSQL uses the durable unique lease row, unique plan/key constraints and short transactions. Schema bootstrap uses the existing transaction-scoped PostgreSQL advisory lock, including new control tables, so simultaneous cold starts serialize table creation. Metadata plans, receipts, key and revision identities survive an empty scratch root. Do not rotate/delete the stored HMAC key without an explicit migration: existing plans authenticate against it.

## Recovery walkthrough

1. Read `receipt KEY`, pipeline status, logs and audit. A terminal `failed` receipt is never retried automatically. Fix the cause, then create and review a new plan with `allowed_operation=update` and a new key.
2. For `executing` after a controller crash, stop the original controller and local worker, or stop the cluster operation and inspect any admitted CronJob/Job. Inspect actual SQL/Parquet output and cluster objects. The control plane cannot infer that external effects did not occur.
3. Only after both controller and worker are stopped, run `recover-release KEY --confirm-worker-stopped` (or protected recovery API). Recovery marks the reserved revision and receipt failed with `interrupted`, records an audit event and removes only the receipt's matching operation row. It does not delete output or relaunch a worker. A different active operation prevents recovery.
4. Review a new plan. The failed revision remains evidence; the next apply creates the next revision. Existing SQL partition keys make writes idempotent, but external systems and Spark overwrite still require operator inspection.

There is no automatic time-based lease stealing. Confirmation is a trusted operator assertion, not proof supplied by Kubernetes. Confirming while the original process remains runnable violates the recovery precondition. Recovery and terminal-outcome writes lock the receipt row so concurrent recovery requests do not duplicate recovery audit events.

The legacy synthetic demo can recover its own old seed attempts automatically. As soon as any Sentinel plan exists for a pipeline name, that automatic lease deletion is disabled for the name, even if the plan is expired or unapplied. This protects a release controller paused between acquiring its operation row and reserving its receipt. If the controller died in that pre-receipt gap, there may be no receipt to recover: a trusted database operator must first stop controller/worker, inspect the pipeline and operation row, and conditionally remove only that exact observed `(name, started)` row using the existing metadata runbook. Never delete by age or pipeline name alone. No worker effect has been authorized until the atomic receipt/revision reservation commits.

## Threat model and limits

The database, installed program, operator environment, filesystem and bearer-token holder are trusted. The API accepts data with closed connectors, never executable code, URLs, templates, DSNs or commands. SHA-256 gives the review copy a content identity; a private metadata HMAC authenticates the stored payload and conceals credential-setting comparisons. A database administrator can read the key and rewrite state, so this is not protection against a database administrator or compromised host. Package/files/environment are expected to remain immutable during a running process; use an immutable image and restart controllers when settings change.

Guarded Kubernetes plans require `PIPEFOUNDRY_WORKER_IMAGE=registry/image@sha256:<digest>`. The string identifies immutable registry content; planning does not contact the registry, validate cluster admission, prove image availability or verify a running pod. Kubernetes success means the API accepted a CronJob, while local success means the fixed worker completed. External source/data drift, live cluster drift, secret changes inside a cluster, RBAC changes, output correctness beyond existing worker quality checks and distributed exactly-once effects are outside the guarantee. Existing HTTPS allowlisting/redirect and fixed-worker execution protections remain in force.

The synchronous API can outlive a hosting request timeout; query the receipt instead of resubmitting a different key. Persistent PostgreSQL is required for ephemeral hosts, plus a configured PostgreSQL output DSN for hosted local execution. Preserve TLS, backups, least-privilege database access and edge rate limiting. The legacy deploy endpoint remains available; enforce Sentinel-only release policy in your gateway/RBAC if your organization requires it.

## Evaluation

`tests/test_releases.py` covers canonical identity, tampering, policy, expiry, stale state, changed artifacts, operator/code changes, idempotent retry, actual worker failure and interrupted-attempt recovery. `tests/test_release_races.py` starts two independent Python processes and actual workers, records launch attempts, and checks one reserved revision/receipt/worker for same and different keys. It also verifies lease retention without a transaction spanning execution, and PostgreSQL plans/receipts across cold scratch roots. `tests/test_release_interfaces.py` executes authenticated HTTP and CLI contracts including whole-review-file tampering.

Run `python scripts/verify_sentinel.py` in the repository venv for the full suite against local Docker PostgreSQL port 55435. The evaluator captures credentials in memory and creates only `pipefoundry_sentinel_test`, using `template0` with `C` collation to avoid modifying the existing container's collation metadata. Evidence is saved with defensive credential redaction. Build `docker build -t pipefoundry:sentinel .`, then run `python scripts/smoke_sentinel_image.py` for real HTTP plan/apply/retry and native runtime inventory. No remote deployment or hosted Sentinel behavior is claimed.

For the full installed Python 3.15 package plus real PostgreSQL, build `docker build --build-context test-sources=./tests -f scripts/Dockerfile.sentinel-tests -t pipefoundry:sentinel-tests .`, then run `python scripts/verify_sentinel.py --native-image pipefoundry:sentinel-tests`. The evaluator joins only the existing local PostgreSQL container's network namespace and passes its isolated test DSN by environment name, never command-line value. The shipped image stays free of test tools.

Verification on 2026-10-30:

| Evidence | Result and scope |
|---|---|
| [Final installed-package + PostgreSQL suite](../evidence/sentinel-native-postgres-tests.txt) | **85 passed, 5 skipped**, Python 3.15.1, real local PostgreSQL; includes same/different-key two-process launches, cold roots, partial render recovery and demo lease protection |
| [Final demo recovery regression](../evidence/sentinel-postgres-focused-tests.txt) | **1 passed, 1 skipped**, real PostgreSQL guard; the SQLite fixture intentionally skips a PostgreSQL-only demo |
| [Host PostgreSQL suite](../evidence/sentinel-postgres-tests.txt) | 84 passed, 3 skipped, earlier checkpoint before the final demo guard; final complete coverage is the native suite above |
| [Native image HTTP](../evidence/sentinel-native-http.json) | Authenticated plan/apply/retry, one revision, three valid SQL rows; UID 10001, no shell/mount/package tools |
| [Bandit](../evidence/sentinel-bandit.json) | Zero findings; Ruff and `pip check` also passed |
| [Hosted read smoke](../evidence/sentinel-hosted-read-smoke.json) | Existing `/health/ready` and read-only `/demo` HTTP 200; Sentinel was **not** deployed |
| [Code line accounting](../evidence/sentinel-loc.json) | +675 production Python lines, +388 tests, +216 evaluator lines; tokens exclude comments, blank lines and standalone docstrings; generated files excluded |

The final native suite's five skips are the SQLite cold-root case, SQLite demo recovery case, opt-in Docker inventory test (covered separately by the real image HTTP inventory), optional Spark runtime, and a TLS fixture requiring an `openssl` command-line tool absent from the minimal test runtime. Host PostgreSQL tests exercised that TLS fixture. No real Kubernetes cluster or new Spark run is claimed. Initial persistent-database test-key collisions were fixed by giving each test invocation unique global keys; the production refusal to rebind a key was correct. Partial-render and demo automatic-reclamation defects each received a failing regression before the fix and passed afterward.

The final shipped local image is `pipefoundry:sentinel`, ID `sha256:0b2766f370cbe7429e7b826f488e21a5d678fce1c1bbc5d1c1980e24e42e6a5e`, 41,408,171 bytes. [Build output](../evidence/sentinel-image-build.txt) records the pinned runtime build. No remote push or deployment was performed. Existing hosted operation uses PostgreSQL metadata/output environment settings and an API token; its public routes remain separate from authenticated Sentinel control routes.
