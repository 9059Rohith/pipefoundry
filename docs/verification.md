# Verification evidence — 2026-10-30

The later public-hosting hardening pass supersedes the original image finding
counts below: **42 host tests passed**, **40 Python 3.15 runtime tests passed**,
and the full fresh-database image scan found **zero vulnerabilities at every
severity and zero secrets**, with no advisory exclusions. Source Bandit and
runtime pip-audit found no issues. Durable PostgreSQL artifacts/audit and genuine
demo execution/backfill/rollback survived a cold container replacement. See
[dated summary](../evidence/public-hardening-summary.json) and the
[hosted runbook](hosted-profile.md) for exact scope, skips and limits. The
separate private Spark image is not covered by the public runtime scan result.

The public Vercel Docker/Neon deployment was subsequently verified at
[rohith-pipefoundry.vercel.app](https://rohith-pipefoundry.vercel.app): actual
HTML, readiness, three SQL rows, zero invalid rows, two backfills and the
rollback audit were observed. Anonymous private access returned 401 and a
valid-token operational read returned 200. Provider database identity TLS,
channel binding and cross-project CONNECT denial were verified. The
[public release evidence](../evidence/public-release-verification.json) includes
twelve warm sequential HTTPS measurements with their limited sampling scope.

Verification ran locally on Windows with Python 3.12, Docker Desktop 28.5.1 and
Java 17, plus a real Linux Spark container. These are observed results; cloud
provisioning, live Kubernetes and remote CI are separate acceptance boundaries.

| Check | Observed result | Evidence |
|---|---|---|
| Full host pytest with real PostgreSQL | **26 passed, 1 skipped**, 61.01s; only native Spark test opt-in skipped | `evidence/tests-final.txt` |
| HTTPS → worker subprocess → PostgreSQL | Real ephemeral CA/server; first 503 retried; two deployments leave one normalized row | `tests/test_workloads.py`, full suite above |
| Hardened Linux Spark | **2 rows written/read back**, EUR/USD Gzip-Parquet partitions, exit 0 | `evidence/spark-linux-test.txt` |
| Docker build | Final image built; UID 10001, read-only-root SQLite worker writes 3 rows and SQL quality passes | `evidence/docker-build-final.txt`, `docker-worker-smoke.txt`, `image-identity.txt` |
| Actual Compose API/PG | Both healthy; HTTP auth negative, two deploys, logs, two-date backfill, rollback, teardown; audit has 15 cumulative events after three smoke runs | `evidence/compose-api.txt`, `compose-smoke.json` |
| Ruff | All checks pass; 19 Python files formatted | `evidence/ruff.txt` |
| Bandit | 0 findings | `evidence/bandit.json` |
| Python dependency audit | 0 known vulnerabilities in installed runtime/dev environment; optional Spark pins also 0 | `evidence/pip-audit.json`, `spark-audit-final.json` |
| Terraform | fmt/check, init and validate pass with AWS 6.71.0 | `evidence/terraform-init-final.txt`, `terraform-validate.txt` |
| Helm | API chart and generated revision both lint/render successfully | `evidence/helm-lint.txt`, generated YAML |
| Kubernetes schemas | Strict validation: 5 API resources + 2 pipeline resources, 0 invalid/errors/skipped | `evidence/kubeconform.txt`, `kubeconform-pipeline.txt` |
| IaC security | Trivy 0.76.0 embedded checks, 0 HIGH/CRITICAL findings; no AWS plan/state involved | `evidence/trivy-config.json` |
| Container vulnerability scan | 44 HIGH/CRITICAL package findings with **0 available fix versions**, using cached 2026-10-20 DB; initial older base had 119 | `evidence/trivy-image-final.json`, `trivy-image.json` |
| Airflow 3 artifact | Generated public SDK/standard-provider DAG parses as Python | `evidence/airflow-syntax.txt` |
| Benchmarks | 100 samples/stage and 30 real full deployments; raw samples retained | `evidence/benchmark.json` |

## Measured performance

Nearest-rank percentiles in milliseconds, sequential samples on local disk.
Full deployment includes metadata writes, checksums/rendering, child interpreter
startup/imports and real SQLite upserts/quality checks for a three-order fixture.
The shared workstation was also running verification work; this is not an
isolated performance laboratory or production SLA.

| Stage | Samples | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| Validate |100|0.0662|0.1676|0.2308|
| Construct templates |100|0.0147|0.0398|0.0944|
| Render files/checksums |100|100.7083|206.0233|266.3096|
| Full local deployment |30|1831.6631|2653.4919|2934.7911|

Reproduce with `python scripts/benchmark.py`; machine contention, filesystem,
antivirus and cold caches affect results. A 30-sample p99 is the slowest sample
under this nearest-rank definition. No EKS/Airflow/API throughput was inferred.

## Runtime boundaries and fixes found

Native Windows Spark was actually attempted after installing PySpark 4.0.1 and
Java 17. Its JVM failed creating a Netty event-loop child due to a Windows
Unix-domain socket `Invalid argument: connect`. This is retained in
`evidence/spark-test.txt`; the skipped host marker must not be read as a passed
native Windows test. The same transformation was then run genuinely in Linux,
with a 2 GiB / 2 CPU limit, read-only root and noexec tmpfs.

The first Linux attempt exposed Snappy extracting a shared library to the noexec
temporary mount. Switching the Parquet codec to Gzip removed that requirement.
The final real run wrote two `.gz.parquet` files and read them back with Spark.
Both failing and successful logs are retained. Kubernetes worker artifacts also
point Java temporary storage at their writable bounded scratch volume. The
standalone network-installing `Dockerfile.spark` is provided but the locally
verified image used installed pure-Python/JAR package build contexts to avoid a
second 434 MB download; the exact helper Dockerfile/command is in the repository.

Other test-found defects fixed during development: canonical child paths could
still escape through symlinked data/revision roots, and SQLite's own connection
context manager did not close handles, breaking Windows temporary-directory
cleanup. Dedicated regressions now enforce both behaviors. The initial
pre-implementation suite observed 10 failures for missing platform modules; further
red/green logs cover security, TLS, cluster argument boundaries and benchmarks.

Independent review also reproduced two defects before fixing them: four red
tests showed teardown omitting older cluster workloads after render/local/failed
revisions, and a raw non-ASCII bearer header producing HTTP 500. The platform now
persists namespace targets before apply, independent of artifact history, and
compares bearer bytes in constant time. Regressions verify process restart,
namespace changes, partial apply/deletion failures, retry cleanup, HTTP 401 for
non-ASCII credentials and HTTP 503 for blank token configuration. These checks
are included in the final 26 passing host tests; `review-red.txt` retains the
original failures.

The final API image uses the digest-pinned current local official Python 3.12-slim
base and removes pip/build tools after installation. The image scan retains all 44
unfixed findings rather than treating an ignore-unfixed gate as a clean scan.
The cached advisory DB is ten days old; rerun with a fresh DB before release.
CI is configured to fail on fixable HIGH/CRITICAL image findings and dependency
advisories. The scanner's embedded IaC checks and partially unknown Terraform
variables do not establish correctness of a live IAM/network deployment.

Terraform initialized from a locally mirrored AWS provider archive whose SHA256
was checked against the official release. The lockfile includes the local Windows
package hash plus official Windows/Linux ZIP SHA256 values, recorded in
`evidence/provider-checksums.json`. Default CI uses the ordinary official registry.
No AWS credentials, Terraform plan/apply, actual EKS cluster, CSI integration,
NetworkPolicy enforcement test, Airflow scheduler run or live CronJob acceptance
is claimed. Missing/unreachable kubectl operations fail and persist failures;
the cluster argument-boundary test uses an explicit external-tool double.

Remote GitHub Actions execution is currently blocked by an account-level runner
restriction. The workflow configuration and local results are available; no
remote CI pass is claimed. Publication is handled separately by the parent task.
