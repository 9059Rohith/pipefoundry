# Requirements traceability and interview notes

| Requirement | Implementation | Evidence / limitation |
|---|---|---|
| Self-service config | `models.py`, CLI validate, API Pydantic request models | Injection/traversal/cron/resources/compatibility tests |
| CLI + control plane | `cli.py`, `api.py` | Real CLI subprocess and FastAPI lifecycle tests |
| Versioned deployment | `render.py`, `engine.py` | Numbered artifacts, checksums, monotonic rollback tests |
| Helm/Kubernetes | Concrete CronJob+ConfigMap, generated Helm revision, control-plane chart | Helm lint/template and kubeconform; live cluster acceptance is separate |
| Airflow | Generated Airflow 3.3.2 DAG with public SDK, standard provider, fixed callable, dates/retries/timeout | Python compile/AST; Airflow scheduler not installed locally |
| Deploy/status/logs | Local execution, kubectl apply/get and bounded pod logs | Local execution real; cluster subprocess argument-boundary test uses a controlled external-tool double |
| Backfill/rollback/teardown | Inclusive bounded dates, forward config revisions, label-scoped deletion | Real SQL partition counts and preserved artifacts/audit tests |
| Audit and concurrency | SQLite audit, checksum anchor, cross-process operation rows | Integrity, locking and connection-close regressions |
| Python API → PostgreSQL | HTTPS fetch, bounded retries, normalization, parameterized upsert, SQL quality | Real TLS503→success source, worker subprocess, PostgreSQL integration |
| PySpark JSON → Parquet | Explicit schema, validation, normalized currency partitions, read-after-write | Optional runtime test; exact observed status in verification.md |
| AWS IaC | Two-AZ network, private EKS, IAM/IRSA, encrypted disks/secrets, logs | fmt/init/validate evidence when provider available; no AWS apply |
| Container hardening | Non-root Docker; probes/security/resources/NetworkPolicy in Helm | Docker smoke + rendered schema validation |
| API security | Fail-closed bearer auth, size limit, safe paths, connector allowlist | Negative tests and security.md residual boundaries |
| Actual percentiles | `scripts/benchmark.py` | Raw samples + p50/p95/p99 in evidence/benchmark.json |
| Dependency assurance | Runtime/dev/Spark pins, Ruff, Bandit, pip-audit, CI | Versioned reports; scans are point-in-time evidence |
| Operations and communication | README, ADRs, security, runbooks, plan, interview Q&A | Operator prerequisites explicitly documented |

## Questions to prepare for

**How does configuration become a running workload?** Validation produces a
closed typed model. The platform reserves a revision, renders and hashes concrete
artifacts, then executes a fixed child module or applies Kubernetes objects.
Success is only reported after the relevant external step succeeds. Metadata and
job observations are distinct from data correctness.

**What makes ingestion idempotent?** `(partition_date, id)` is the primary key.
Parameterized `INSERT ... ON CONFLICT ... DO UPDATE` commits a deterministic
latest value for repeated IDs. SQL quality checks run before the same transaction
commits. Retries are at-least-once; uniqueness/upsert prevents duplicate final
rows. This does not make a non-idempotent upstream API safe.

**Why integer cents?** Floats can change financial amounts through binary
rounding. The contract accepts integer minor units and three-letter currency
codes. Never aggregate across currencies without an explicit FX conversion/date.

**Why does local deployment ignore the schedule?** It is a real one-shot
execution path for development and review. Kubernetes/Airflow own scheduling.
Pretending that a stored cron string is an active scheduler would misrepresent
the operational behavior.

**How would this scale?** Move jobs into a durable queue with run/partition IDs,
lease renewal, cancellation and reconciliation. Use PostgreSQL metadata, tenant
authentication/RBAC and quotas, per-workload service accounts, object-store
artifacts and signed worker image digests. Keep admission validation in front of
the queue. Benchmark concurrent workload throughput and failure recovery before
adding API replicas.

**How does rollback differ from data recovery?** Rollback creates a new
configuration revision from a verified older spec. It does not reverse already
committed rows or restore an old worker image/environment. Database PITR/backups
and immutable datasets handle data recovery; Git/IaC handles infrastructure.

**Why can Spark duplicate handling differ?** Python's input array has a stable
order, so last observation can win. A distributed Spark dedup without an event
version/order column is nondeterministic; this sample rejects duplicate IDs.
Production should define a source version and deterministic window ordering.

**How do you prevent SSRF?** Pipeline callers cannot submit URLs. Administrators
define connector destinations with HTTPS and exact hostname/port allowlists.
Redirects, URL credentials and nonpublic IP literals are rejected, proxies are
disabled and responses bounded. DNS remains trusted; enforce egress CIDRs or use
a hardened egress proxy for production DNS rebinding protection.

**Why no shell=True?** Argument lists preserve argument boundaries; a name like
`orders; rm ...` cannot become a second command. Closed enums and resource-name
validation also block executable/template injection before rendering.

**What can fail after Kubernetes accepts the CronJob?** Image pulls, missing
secrets, PVC scheduling, forbidden egress, database outages, quota/resource limits
and bad source data. Live status/logs/events and job deadlines expose these. The
control plane does not equate API acceptance with successful data ingestion.

**What did tests find during the build?** Traversal-safe child paths still
escaped when the *root subdirectory itself* was a symlink; root containment now
covers that case. SQLite's connection context manager commits/rolls back but
does not close a connection, which caused benchmark cleanup failure on Windows;
the wrapper now closes deterministically. Both failures have regressions.

**How credible are the performance numbers?** They are actual sequential wall
times on the recorded Windows host, with raw samples and nearest-rank percentiles.
Template construction excludes disk IO, rendering includes file writes, and full
local deployment includes metadata/rendering/import/process/SQL overhead. A small
sample p99 is noisy, and these are not production EKS latency/throughput SLAs.
