# PipeFoundry implementation plan

2026-10-30. Scope: a deployable, auditable pipeline platform for the OpenFX Data
Engineering + DevOps Intern portfolio. Execution is authorized without approval
gates; external cloud/publication is owned by the parent task.

1. Write negative and integration tests, observe failures, implement typed bounded
   configuration and immutable revision rendering.
2. Implement transactional SQLite metadata/audit and CLI/API lifecycle with
   fail-closed bearer authentication. Local execution is synchronous, bounded,
   real workload execution; cluster operations use explicit subprocess arguments.
3. Implement fixture/API ingestion, PostgreSQL idempotent upserts, SQL quality
   checks and Spark JSON-to-Parquet. Exercise real integration runtimes available.
4. Render Kubernetes CronJob, Helm chart and Airflow DAG. Add AWS EKS private
   networking/IAM Terraform and secure API deployment Helm chart.
5. Verify full test suite, lint, security/dependency scans, render/build checks,
   benchmark measured p50/p95/p99 and document exact runtime limitations.
6. Document architecture, ADRs, threat model, runbooks, interview questions and
   requirements traceability. Initialize isolated Git repository codex/initial-build.

## Constraints and decisions

- No arbitrary scripts, SQL, URLs, images or shell strings in submitted configs.
- Connector URLs and database DSNs are administrator environment variables, never
  revision data. HTTP connectors reject redirects, credentials and nonallowlisted
  hosts; fixture inputs allow offline verification.
- API mutation responses never equate manifest generation with deployment success.
- No AWS resources will be created in this build. EKS examples need operator
  configuration, cost review and actual cluster acceptance testing.
- Persist statuses and failures; rollback creates a new monotonic revision.

## Progress ledger

| Phase | Evidence |
|---|---|
| Plan | Created before production implementation |
| Red tests | Observed 10 initial failures before implementation; security, TLS, benchmark and cluster-boundary red logs retained |
| Core/API/CLI | 26 host tests passed; actual CLI/worker execution, auth, revisions, rollback/backfill/audit; Docker Compose HTTP acceptance passed |
| PostgreSQL/Spark | Real TLS 503 retry→worker→PostgreSQL idempotence/quality passed; Linux / Java 17/PySpark 4.0.1→GzipParquet read-back passed; native Windows socket failure explicitly recorded |
| Security/benchmark | Ruff/Bandit/pip-audit pass; strict 7-resource schema validation; `terraform validate` passes; image 44 unfixed H/C, 0 fixable; 100 stage / 30 execution samples recorded |
| Documentation | README, architecture/ADRs, threat model, runbooks, requirements/interview Q&A, verification and CI authored |

## Completion evidence and external limits

See `docs/verification.md` and the raw `evidence/` directory. Real fixes found by
testing include root-symlink containment, deterministic SQLite handle closure,
and replacing Snappy with Gzip for a hardened noexec temporary mount. Airflow
targets the current 3.3.2 public SDK/standard provider; syntax is checked, scheduler
execution is not claimed. Terraform uses AWS 6.71.0 with official Windows/Linux
archive hashes; no cloud apply occurred. Native Windows Spark fails in Java's
Unix-domain socket initialization; a real Linux container validates the workload.
Remote CI is blocked by an account-level runner restriction; no remote pass is
claimed. Parent task owns external publication and any cloud work.
