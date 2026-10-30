# Public hosting hardening and durable profile

Authorized scope: security/container fixes and an opt-in PostgreSQL durability
profile for an ephemeral, autoscaled container host. Root owns deployment,
credentials, provider resources and publication. No workflow edits or pushes.

1. Refresh advisory DB; retain original full image scan and package inventory.
2. Remove unused vulnerable userland through a supported minimal image, retaining
   OS package metadata and the same full scanner configuration. Test actual
   Python/SQL/TLS/API behavior and absence of shell/mount/package-manager commands.
3. Reproduce public-boundary flaws before fixing: authenticate before consuming
   bodies, reject declared oversize bodies and enforce a total upload deadline.
4. Add PostgreSQL metadata/artifact/log persistence using existing psycopg, with
   real cross-instance/restart tests. Keep SQLite local default unchanged. Hosted
   local executions require PostgreSQL data outputs, not ephemeral local data.
5. Verify full host/container suites, actual API/SQL flows, dependency/source
   scans and a full current-DB image scan. Record residuals and runtime versions.

Progress: current DB downloaded from public ECR (UpdatedAt 2026-10-30). Original
image: 44 HIGH, 58 MEDIUM, 61 LOW, 4 UNKNOWN findings. Minimal Wolfi candidate:
zero vulnerabilities and secrets with package metadata retained. Host boundary
regressions observed red and then passed. PostgreSQL durability, cross-instance
locks, concurrent schema initialization, artifact bounds and interrupted demo
recovery all passed. The opt-in HTML/JSON console uses genuine synthetic worker,
SQL quality, backfill and rollback receipts. Final host suite: 42 passed, 1 opt-in
Spark skip. Actual Python 3.15 runtime: 40 passed, 3 explicit runtime/tool skips.
Cold-container replacement preserved revision, artifacts and audit receipts.
Final full current-DB image scan: zero vulnerabilities/secrets at every severity.
Browser automation inventory was empty; HTML/CSP/escaping and HTTP verified.
