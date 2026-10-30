# Deployment preview

Implement a metadata-only deployment preview for the authenticated API and trusted
local CLI. Reuse the exact deployment request model and hosted output restrictions.
Compare default-expanded configuration (normalizing cron whitespace) and executor
against the latest recorded revision. Return create/update/no-op, current revision
and status, operation-in-progress indication, deterministic fingerprints and at
most twelve known leaf-field changes. Return no config values, credentials or
artifact contents; field paths make changes reviewable without leaking payloads.

No-op requires a succeeded/deployed current revision and no active operation;
other existing states need an update even when the desired specification matches.
The result is an advisory metadata snapshot, never live drift detection, a resource
availability check or an atomic promise about the following deploy. Deploy itself
retains its existing explicit revision/execution behavior.

1. Write failing API/CLI/engine and PostgreSQL fresh-root tests; record red run.
2. Implement SELECT-only comparison without artifact restore/render/worker/locks.
3. Verify host and pinned Python runtime suites, with real PostgreSQL integration.
4. Measure preview/local execution and authored config/generated artifact counts.
5. Rewrite README around reproducible workflows, evidence, boundaries and review.

Completed: CLI plus authenticated typed API preview, canonical bounded path-only
comparison, one-statement latest-revision/operation snapshot on SQLite and
PostgreSQL, sixteen new regression cases, README/runbook/architecture updates and
recorded benchmarks. Final host suite: 58 passed / one optional Spark skip; pinned
Python 3.15 runtime: 56 passed / three documented external-tool/runtime skips.
Ruff lint/format, Bandit and link/whitespace checks passed. Review red/green and a
resolved shared-test-table count isolation failure are retained as evidence.
No hosting mutation, workflow edit or push was performed by this implementation.
