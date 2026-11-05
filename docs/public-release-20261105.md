# Recruiter demo verification — 5 November 2026

PipeFoundry's GitHub quota recovery and bounded AI evidence fixes are deployed at
[the public workbench](https://rohith-pipefoundry.vercel.app/workbench/overview).
The production alias was verified against deployment
`dpl_J3TWbtZPbCkqCo1TTg8EBj4zjVkW`, source commit
`baf34f88c3be` (including cache implementation `261040279aa9`).
The staged production container passed readiness before promotion. The deployment
inspection reported Ready in iad1; its non-root image is pinned by digest
`sha256:d227baa96358366f1e24d8a16b63810bc53d6e1c852fe36645679d7ff646a21e`.
The post-promotion error-level log query returned no logs. This is a release
check, not evidence of uninterrupted availability or a hosted CI success.

Only PipeFoundry application code changed in this release. The other three
existing public deployments were retested against their canonical domains.

| Public app | Verified recruiter workflow |
| --- | --- |
| [Settlement Recon](https://rohith-settlement-recon.vercel.app/workspace/history) | Historical USD/INR replay returned four paired source observations for 1–7 January 2025 |
| [FluxLake](https://rohith-fluxlake.vercel.app/workspace/replay) | Retained publication reconstruction checks agreed; historical archive evidence remained visible |
| [DataGuard](https://rohith-dataguard.vercel.app/console/checks) | Actual 500-repository benchmark published under baseline policy and quarantined under strict policy; 96 and 177 failing rows respectively |
| [PipeFoundry](https://rohith-pipefoundry.vercel.app/workbench/overview) | Typed draft validation, CronJob manifest, static release review and existing Kubernetes rollback evidence remained accessible |

## Verification evidence

- [Fourteen public API checks](../evidence/public-api-20261105.json) passed after
  the final promotion: database readiness, source reads/replay, review and
  rejection of anonymous operator mutations with HTTP 401.
- [Eight browser workflows](../evidence/public-browser-20261105.json) passed at
  390 px and 1440 px in Chromium. No page errors, console errors, provider failures
  or horizontal page overflow were observed in these flows. PipeFoundry was
  checked again after the final promotion; the unchanged apps retain their checks
  from earlier in this release session.
- [Thirty-one public GitHub responses](../evidence/github-public.json) all returned
  HTTP 200 using the shared PostgreSQL cache. Each source URL, timestamp and body
  SHA-256 was verified. Two were fresh and 29 were genuine dated captures during
  the actual upstream quota cooldown. This does not claim 31 fresh GitHub fetches.
- [Twelve additional browser page checks](../evidence/public-github-pages-20261105.json)
  covered repository, workflows, runs, releases, commits and the first returned
  run's jobs at both widths. Empty releases and failed runs are the real source
  outcomes. [Mobile](../evidence/github-run-mobile.png) and
  [desktop](../evidence/github-run-desktop.png) captures show the retained-data notice.
- [All four public AI endpoints](../evidence/public-agents-20261105.json) returned
  actual Gemini answers over public HTTPS without an operator token. PipeFoundry
  was called again after the final fix: its answer included the server-added
  dated-evidence notice, exact source observation time and a real failed run link.
  Each request consumed a real free-tier demo allowance.
- The [full regression log](../evidence/github-cache-regression.txt) records 135
  passes and four environment-specific skips before the final small policy/agent
  changes. The affected cache, workbench and public-agent suite then passed all
  **33 tests** after the final code change. Six JavaScript tests, Ruff,
  formatting checks and Bandit's high-severity scan passed.
- [Pinned dependency audit](../evidence/github-cache-dependency-audit.json) found
  no known vulnerabilities in the listed runtime dependencies. It is not a scan
  of the new remote container or proof of complete security.
- The [native PostgreSQL experiment](github-shared-cache-proof.md) verified
  one refresh across eight instances, persistence through an actual restart,
  controlled HTTP 429 handling and expired-owner fencing. Failure injection uses
  recorded genuine source bodies; it does not populate public demos with made-up
  data or manufactured success outcomes.

## Operating boundaries

Public browsing, validation, manifest review and bounded AI are recruiter-facing.
Execution, releases, backfills and rollback remain authenticated operator actions.
The public workbench does not launch cloud resources on a recruiter's behalf.

GitHub still controls its upstream quota. Cached data is explicitly dated and
must have been validated within 24 hours; after that, unavailable evidence returns
an error rather than fabricated records. AI has fixed repository/tool scope and
persistent visitor/global allowances, and may return a retry interval when those
limits are reached. Original workflow failures are preserved; no green hosted CI
claim is made.

Reproduce the 31 public inspection checks without provider credentials:

```powershell
.venv/Scripts/python.exe scripts/verify_public_github.py
```

The verifier only reads public views, although normal application cache admission
and refresh coordination still occur. See [the cache policy](github-rate-limit-recovery.md)
for freshness, bounded storage and failure behavior.
