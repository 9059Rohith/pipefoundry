# Public API image hardening, 2026-10-30

The original Debian public API image had 44 HIGH findings under the current
advisory database. These were eight unique CVEs, often reported against several
binary libraries built from the same source package. The installed inventory,
loaded shared libraries and complete unfiltered scan are retained in
`evidence/security-before-inventory.json` and `security-before-image.json`.

| Source / advisory | Actual old runtime relationship | Resolution |
|---|---|---|
| util-linux: CVE-2026-76642, CVE-2026-78408, CVE-2026-78409, CVE-2026-78410 | mount/nsenter utilities and associated binary libraries were installed; source-level matches repeat across related packages | Entire Debian util-linux family absent in final runtime |
| libacl: CVE-2026-54369 | ACL symlink behavior in installed library; Python workload does not need ACL tools | Debian library absent |
| ncurses: CVE-2025-69720 | infocmp command overflow; not a pipeline feature | infocmp and Debian ncurses packages absent |
| systemd: CVE-2026-16742 | source-level match on installed libsystemd/udev; vulnerable systemd-homed daemon was absent | Neither Debian systemd libraries nor daemon retained |
| Perl: CVE-2026-9538 | source-level Archive::Tar advisory against Perl package; application does not execute Perl archive processing | Perl and its archive userland absent |

This classification distinguishes reachable tools from source-package matches;
it does not suppress either class in the scan. Primary advisory references:
[Debian util-linux](https://security-tracker.debian.org/tracker/CVE-2026-76642),
[nsenter advisory](https://security-tracker.debian.org/tracker/CVE-2026-78408),
[mount advisory](https://security-tracker.debian.org/tracker/CVE-2026-78409),
[related util-linux advisory](https://security-tracker.debian.org/tracker/CVE-2026-78410),
[ACL](https://security-tracker.debian.org/tracker/CVE-2026-54369),
[ncurses](https://security-tracker.debian.org/tracker/CVE-2025-69720),
[systemd upstream](https://github.com/systemd/systemd/security/advisories/GHSA-jm29-p7hh-vjhv),
[Perl](https://security-tracker.debian.org/tracker/CVE-2026-9538).

## Supported minimal replacement

The public `Dockerfile` uses supported Chainguard Python builder/runtime images:

```text
cgr.dev/chainguard/python:latest-dev@sha256:95d8cc85fad8acc8ebad357e1972f2a975c498a65406cd9b00bb2233371a94a2
cgr.dev/chainguard/python:latest@sha256:bf06e09413bec94d6489f0be783b8f9349339907b89e0f759d190d0b95ab2d8f
```

The final runtime copies only the installed application virtual environment and
an empty owned state directory. It retains its Wolfi package database. Trivy
inventoried 30 OS packages and Python metadata rather than treating it as an
unknown bare filesystem. Python 3.15.1, OpenSSL 4.0.3, SQLite 3.54.1, psycopg
native wheels, HTTPS/SQL behavior and the public API were exercised. Runtime UID
is 10001. The executable contract rejects shell, mount/umount/nsenter, infocmp,
Perl, apt/apk and pip. PyYAML's supported pure-Python implementation is used
because the pinned release has no CPython 3.15 native wheel; SafeLoader and
SafeDumper remain the application boundary. The host Python 3.12 suite also
passes. The separately optional Java/Spark image is not this image.

The built manifest is
`sha256:ed36ea380b472a1438c647c8557369433f6a9d4616be2e4c9acd268b03b6a493`;
its platform config is
`sha256:cc1f99a5518e5d785f74e56c835ab1215ae6968635ff289a5c95eb5ab4bb7f59`.
Build attestations explain the distinction. These are local verification image
identities; a hosting provider may produce another build identity from source.

## Reproduce the full scan

The database was successfully downloaded from the official public ECR mirror,
UpdatedAt `2026-10-30T13:06:28.139593044Z`, and then held constant between baseline
and candidate. No ignore file, ignore-unfixed option, severity filter or package
metadata deletion was used. Trivy 0.76.0 ran vulnerability and secret scanners:

```powershell
docker build -t pipefoundry:security .
docker image save -o .runtime/security-after.tar pipefoundry:security
docker run --rm -v "${PWD}/.runtime:/input:ro" -v pipefoundry_trivy_cache:/cache `
  aquasec/trivy:latest image --cache-dir /cache --skip-db-update --no-progress `
  --scanners vuln,secret --format json --input /input/security-after.tar
```

Use `--download-db-only --db-repository public.ecr.aws/aquasecurity/trivy-db:2`
with the same cache to refresh before a future scan. The final full result is
zero vulnerabilities at all severities and zero secrets. There are no residual
unfixed HIGH/CRITICAL findings in this public runtime under this dated database.
Ruff, Bandit and runtime lockfile pip-audit also passed. Because the lock already
pins all transitive versions, the audit used `--disable-pip --no-deps` to avoid a
redundant environment resolution; it still queried each pinned package's public
advisories. A previous resolution-based attempt timed out against PyPI, and is
not represented as a successful check.

The regression suite includes real Docker non-root/read-only execution and
real PostgreSQL worker ingestion, durable metadata, backfill and rollback. Scan
cleanliness is not proof of absence of unknown vulnerabilities. Rebuild and scan
on an update cadence, update immutable digests deliberately, and rerun both
runtime versions' tests before promotion.
