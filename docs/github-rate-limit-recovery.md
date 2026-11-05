# Public GitHub inspection without request storms

The former 60-second process-local cache did not coordinate serverless instances.
Repository, workflow and run views could each spend the same anonymous GitHub
quota, and only repository metadata had a retained source response.

The workbench now persists responses and refresh ownership in the existing
PostgreSQL metadata database. A 30-second lease serializes upstream refreshes;
short database transactions never remain open during HTTP. Completion is fenced
by lease ownership. The global token bucket admits eight initial requests and
refills one token every 90 seconds (40/hour thereafter). This accommodates five
collections and three job details on a first visit. Other applications sharing
the provider IP can still consume its quota.

Responses are fresh for ten minutes. Conditional requests use ETags; 304 updates
validation time while retaining the original body and observation timestamp.
Anonymous conditional requests still count toward GitHub's quota. HTTP 403/429
pauses every view until the longest applicable Retry-After/reset deadline, with
a minimum 60-second pause. HTTP 200 with no remaining quota also starts a pause.
Transient upstream failures defer refreshes for 60 seconds.

During a pause, a response validated within 24 hours remains readable with its
original source URL, observation time, validation time, content SHA-256 and stale
notice. Thirty-one genuine responses seed cold starts, including the actual
empty releases list and failed workflow runs. No successful runs or executions
are invented. Authoritative 404/private responses revoke that resource instead
of returning old evidence. Expired or absent evidence returns a bounded error.

Storage is bounded to 128 request keys. The provider origin and view suffixes are
fixed by server validation; users cannot supply arbitrary fetch URLs. Only public
anonymous data is fetched. Database failure never bypasses coordination with an
uncontrolled upstream request: a usable dated capture is returned, or HTTP 503.
The hosted cache requires PIPEFOUNDRY_METADATA_DSN; local development can use
PIPEFOUNDRY_GITHUB_CACHE_DB or in-process SQLite. Credentials remain server-side.

Verification on 2026-11-05:

- Full regression run: 135 passed, four documented environment-specific skips.
- After increasing the initial bucket from four to eight, the affected workbench
  and cache suite passed all 24 tests, including the new eight-page first-visit
  regression. The regression first failed against the smaller bucket.
- Six JavaScript tests passed; Ruff checking/formatting, Bandit high-severity scan
  and all 31 source capture hash checks passed.
- Native PostgreSQL proof exercises eight independent cache instances, a real
  database restart, controlled rate limiting and expired-owner fencing. See
  [the proof](github-shared-cache-proof.md). Controlled test responses are failure
  experiments, not data displayed as fresh provider responses.

References: [GitHub REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
and [REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api).
