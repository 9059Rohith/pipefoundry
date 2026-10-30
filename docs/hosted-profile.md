# Ephemeral container hosting

The live free-tier deployment is the
[PipeFoundry HTML console](https://rohith-pipefoundry.vercel.app), with
[JSON receipts](https://rohith-pipefoundry.vercel.app/demo) and
[readiness](https://rohith-pipefoundry.vercel.app/health/ready). Vercel runs the
actual OCI Docker container and Neon provides persistent PostgreSQL. Free
hosting can scale to zero; startup and database wake-up add latency. No cloud
Kubernetes execution is implied by this hosted demo.

The normal CLI/Compose profile keeps SQLite control-plane state on a persistent
local volume. An opt-in hosted profile stores metadata, audit records, operation
locks, immutable artifact bytes, checksums and bounded worker logs in PostgreSQL.
Scratch directories may disappear between requests or container starts. The
platform reconstructs missing revision files from the database and checks their
paths and SHA256 manifest before execution. Existing tampered local files fail
verification instead of being silently replaced.

Configure server-side environment variables; never put credentials in YAML:

| Variable | Purpose |
|---|---|
| `PIPEFOUNDRY_API_TOKEN` | Unique bearer token of at least 32 characters for private APIs |
| `PIPEFOUNDRY_METADATA_DSN` | PostgreSQL metadata connection, preferably a separate database/role |
| `PIPEFOUNDRY_POSTGRES_DSN` | PostgreSQL workload output connection |
| `PIPEFOUNDRY_STATE_DIR` | Writable scratch directory, e.g. `/tmp/pipefoundry` |
| `PUBLIC_DEMO=true` | Explicitly enable anonymous read-only `/` HTML and `/demo` JSON |
| `SEED_DEMO=true` | Start the fixed synthetic demo once; has no effect unless public demo is enabled |

The longer names `PIPEFOUNDRY_PUBLIC_DEMO` and `PIPEFOUNDRY_SEED_DEMO` take
precedence over the two aliases. Public access defaults off. Supply TLS-verified
DSNs using your provider's CA and `sslmode=verify-full`; never disable certificate
verification. Metadata and output may share an isolated project database for a
small demo, with distinct fixed `pf_*` metadata tables. Production roles should
have only the database and table permissions they need. Revoke public database
access and test that unrelated project roles cannot connect.

The deployed DSNs require `sslmode=verify-full`,
`sslrootcert=/etc/ssl/certs/ca-certificates.crt` and `channel_binding=require`.
This verifies the server identity and requires channel binding rather than
merely requesting encrypted transport. The isolated `app_pipefoundry` role owns
only its project database and has NOSUPERUSER, NOCREATEDB, NOCREATEROLE and
NOREPLICATION. Database PUBLIC access was revoked. Actual connection attempts
from unrelated project roles were denied with PostgreSQL SQLSTATE 42501.
Role defaults bound statements to 15 seconds, lock waits to 10 seconds and idle
transactions to 30 seconds. The metadata adapter uses a five-second connection
timeout and a stricter ten-second statement timeout. These provider-side grants
and settings must be reprovisioned explicitly in a new environment.

The Docker image listens on port 8080. Configure the host's target port to 8080.
It runs as UID 10001 without a shell, package manager or kubectl. Run it with a
read-only root, bounded writable `/tmp`, dropped capabilities, no privilege
escalation and provider memory/CPU/concurrency limits. No Docker socket or cloud
credentials belong in the public service. TLS and rate limits belong at the
provider edge. The container has a 64-request concurrency limit, a 32 KiB request
body limit and a five-second total upload deadline. Invalid credentials are
rejected before consuming the body.

## Real demo behavior

On startup the opt-in seed uses the existing Python worker and PostgreSQL sink
to ingest three synthetic orders, deploy a changed schedule, backfill two fixed
dates and roll back to the first configuration. The rendered schedules are
artifacts: this host does not schedule cron jobs. The public console displays
stored worker counts, SQL quality results, backfill receipts, artifact SHA256
and actual audit events. It never fabricates measurements, exposes records or
publishes private pipeline names/logs/credentials. All mutation APIs and the
OpenAPI schema remain authenticated. `POST /demo/seed` also requires the token.

A durable seed lease prevents duplicate startup work. Completed seeds are
idempotent across cold starts. A failed/interrupted synthetic seed retains its
failure audit and can resume after lease expiry. Recovery is restricted to the
reserved fixture-to-PostgreSQL demo pipeline without cluster targets; arbitrary
operator locks never expire automatically. A schema advisory lock serializes
concurrent cold-start initialization and works through transaction pooling.

Until seed completion, `/health/ready`, `/` and `/demo` return 503; `/health/live`
still reports process liveness. Seed errors are logged by exception type without
connection strings. Inspect private audit/log endpoints and database connectivity
before retrying. Public reads cache successful receipts for five seconds and
pending state for two seconds to bound database work.

## Boundaries and recovery

Hosted local execution accepts PostgreSQL outputs only; SQLite and Parquet data
would be lost with scratch storage. The local default still supports both and
the separately verified private Spark runtime. Artifact/log persistence is bounded
to 128 files per revision, 128 KiB per file and 64 KiB captured worker logs.
Pipeline mutation locks coordinate separate service instances through durable
unique rows. A crashed non-demo operation requires operator reconciliation; do
not delete a lock while its worker could still run.

Use provider PostgreSQL backups and retention/quotas for long-running installations.
The service is single-operator, without tenant isolation or a distributed job
queue. An HTTP request runs a bounded worker synchronously; provider termination
can interrupt it. Read the durable audit before retrying; PostgreSQL upserts are
idempotent per order/date. A Kubernetes deployment requires an authorized external
operator installation and is not implied by hosting this API.

## Verified locally, 2026-10-30

The final host suite passed 42 tests with one explicit Spark opt-in skip. The
actual Python 3.15 minimal runtime passed 40 tests with three declared skips
(nested Docker opt-in, Spark opt-in, and the test certificate generator requiring
an OpenSSL command-line binary). The host suite covers the real TLS source,
PostgreSQL ingestion and Docker runtime contract. Separate earlier Linux Spark
evidence remains in the verification report.

A read-only, cap-dropped local container on 127.0.0.1:8096 executed the demo
against real PostgreSQL. Replacing that container with an empty tmpfs preserved
revision 3, its artifact checksum, four audit events and both backfill receipts;
private listing without a token returned 401. Receipts are recorded in
`evidence/hosted-http-before.json` and `evidence/hosted-http-after.json`.
Browser automation had no available browser in the implementation subagent;
HTML escaping, pending state, authentication and CSP were checked by tests and
HTTP. The deploying operator then verified the actual public HTML in a browser
and checked live readiness and PostgreSQL receipts. Anonymous private reads and
mutations returned 401, while an authenticated operational read returned 200.
The public result contains revision 3, three rows, zero invalid rows, two
backfills and four successful audit events including rollback. Strict database
TLS and cross-project connection denial were independently verified. Evidence:
[public release verification](../evidence/public-release-verification.json).

Twelve sequential warm public HTTPS requests from India measured p50 419.385 ms,
p95 2175.270 ms and p99 2175.270 ms using nearest rank. This is a small observed
sample, not a concurrency/load test, service objective or cold-start benchmark.
The two upper percentiles select the same maximum in a twelve-request sample.
