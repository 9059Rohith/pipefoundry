# Security design and boundaries

## Trust and access

The API is a single trusted-operator service. A bearer token of at least 32
characters is required on all private lifecycle/read endpoints; missing/short token
configuration fails closed. Token comparison is constant-time and credentials
are read from environment variables. Health endpoints expose no configuration.
Run behind TLS, request timeouts and per-token rate limits; localhost binding in
Compose is for development. There is no end-user identity, per-pipeline ACL,
tenant isolation, token rotation protocol or distributed admission controller.

The explicit `PUBLIC_DEMO=true` profile exposes only a fixed synthetic pipeline's
HTML/JSON receipts, without records, raw logs, credentials or private pipeline
information. Public access defaults off. See [hosted boundaries](hosted-profile.md).
Authentication occurs before reading request bodies; uploads are limited to
32 KiB and a five-second total deadline. The public HTML has no JavaScript/forms
and a restrictive Content-Security-Policy. Health endpoints expose no DSNs.

The CLI has the caller's filesystem and Kubernetes privileges. Do not expose its
state directory to untrusted users or mount a Docker socket in the API container.
The base API image has neither kubectl nor Kubernetes credentials. Cluster
lifecycle commands run from an authorized operator installation.

## Threats and controls

| Threat | Implemented control | Remaining boundary |
|---|---|---|
| Shell/command injection | Fixed executable/module and argument arrays, `shell=False`; closed transform/connector values; validated resource names | Operator PATH and kubectl binary are trusted |
| SSRF | No URL accepted from pipeline configs; HTTPS URL and host/port allowlist set by administrator; no redirects, URL credentials or nonpublic IP literals; ambient HTTP proxies disabled | DNS and administrator connector settings are trusted; enforce destination CIDRs at egress proxy/NetworkPolicy to prevent DNS rebinding |
| Traversal / symlink escape | Constrained relative paths, canonical root containment for data and revision roots, negative symlink tests | Concurrent privileged filesystem replacement is outside the threat model; directory ownership must prevent it |
| SQL injection | Fixed schema/quality SQL and parameterized record values; no user SQL/table identifiers | Database credentials still need least privilege and TLS in production |
| Resource exhaustion | 32 KiB request/config, 1 MiB response, 10k rows, bounded names/resources/dates, subprocess deadlines, 64 KiB captured logs, CronJob deadlines/TTL, container limits | Authorized callers can create many revisions; storage quotas, reverse-proxy rate limits and retention must be configured |
| Secret disclosure | DSNs/tokens never enter revision configs; worker error output sanitized; environment-based credentials; API uses no-store headers | Operator kubectl diagnostics and arbitrary source data can contain sensitive content; restrict log access and sanitize upstream records |
| Revision tampering | DB-anchored SHA256 checksum manifest checked before execution/rollback | Disk administrators can alter the database; use external immutable backups/signing for stronger provenance |
| Overlapping mutations | Cross-process SQLite operation lock plus thread lock; immutable revision directories | A crashed process leaves an operator-reconciled lock; scheduled/manual cluster jobs can overlap |
| Container privilege abuse | Non-root, no privilege escalation, drop ALL caps, read-only root, seccomp, no SA token, bounded scratch volume | An executing workload still has connector/data privileges by design |
| Lateral movement | Chart NetworkPolicies allow DNS/PostgreSQL and explicitly supplied HTTPS CIDRs; private EKS API | NetworkPolicy requires an enforcing CNI; test denial on the actual cluster |

Allowlisted hostname resolution is deliberately a trusted administrative
configuration. The platform's users cannot choose URLs. A compromised approved
API or DNS zone remains dangerous; route external connectors through an
organization egress proxy with DNS pinning and private-address deny rules. Private
hostname connectors can be intentionally approved by administrators; only literal
nonpublic IP addresses are rejected by the connector itself.

Secrets in Kubernetes are referenced by name, never rendered with values.
Provision `pipefoundry-api` (`token`) and `pipefoundry-connectors` (environment
keys) using an external secret manager. EKS encryption is configured, but workload
IAM, PostgreSQL TLS/user grants and key rotation require operator integration.

## Security verification

The current public API image uses digest-pinned supported Chainguard/Wolfi Python
builder/runtime stages. It removes the Debian utility packages responsible for
the previous 44 HIGH findings rather than hiding advisories. The installed OS
package database remains present and Trivy identifies 30 Wolfi packages plus
Python distributions. No shell, mount/nsenter, Perl, package manager or pip
executable is present. Python SSL/SQLite/PostgreSQL and real worker behavior pass
runtime tests. The separately provided Spark development image is outside this
public-runtime scan result and must be maintained/scanned independently.

With the freshly downloaded advisory database (UpdatedAt
2026-10-30T13:06:28Z), the full image vulnerability and secret scan reports zero
findings at all severities, with no ignored CVEs or severity filter. Scan files,
package inventories and before/after evidence are in `evidence/security-*`.
Zero known findings is a dated observation, not a guarantee of no vulnerabilities.

Tests cover config injection, unknown URL/script fields, path traversal, absolute
paths, resource limits, invalid cron, fail-closed auth, oversize bodies, redirect
and metadata IP blocking, retry bounds, tamper detection, symlink containment,
SQL quality transaction rollback and cross-instance operation exclusion. HTTP
transport doubles are used for deterministic retry/redirect attacks; the
PostgreSQL integration also uses a real TLS source and actual child workers.

Bandit reviews Python source. Two narrow justified suppressions cover importing
subprocess and invoking validated argument lists; they do not suppress arbitrary
findings. Ruff validates code style/errors. pip-audit scans pinned dependencies;
runtime and verification tool lockfiles are separate. Re-run scans on a fresh
advisory database before production. Lockfiles pin versions but are not a signed
software supply-chain attestation.

No sample credentials should be reused outside local verification. Any passwords
visible in integration evidence identify an isolated localhost-only test service,
not an externally accessible account. Real credentials, Terraform state, .env,
local state and downloaded runtimes are ignored by Git.
