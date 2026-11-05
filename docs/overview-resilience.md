# Overview provider outages

On 2026-11-05 the canonical overview returned genuine GitHub responses at both
390px and 1440px. One request for Actions runs returned HTTP 429 while repository
metadata and workflow definitions returned HTTP 200. The backend correctly refused
to substitute evidence older than 24 hours. The overview selector was current.

Repository metadata had an additional frontend failure path: its rejected request
replaced the entire overview with an error, hiding the otherwise independent build
workspace and its metric definitions. Replaying the observed provider error against
that request reproduced zero metric groups and zero editor links in the content area.

The overview now handles metadata failure independently. It shows the provider error
and a retry link, labels unavailable values explicitly, and preserves configuration,
validation, manifest inspection, and any independently available source results.
GitHub HTTP errors, cache timestamps, the 24-hour maximum fallback age, and all
authorization boundaries are unchanged. This does not remove GitHub's rate limit.

## Regression

Start the normal local FastAPI app, then run:

```sh
WORKBENCH_URL=http://127.0.0.1:8125 node scripts/check_overview_outage.cjs
```

The script requires an installed Playwright browser driver. `PLAYWRIGHT_MODULE`
and `CHROME_EXECUTABLE` can select existing installations. It injects only GitHub
failure responses (429 and 502), at 390px and 1440px. Each case asserts four valid
DT/DD metric groups with unavailable values, a visible failure reason, actual public
validation followed by a CronJob manifest, no uncaught JavaScript errors, and no
horizontal overflow. It does not spend AI quota or supply invented source records.

The same regression failed against the original production build and passed all
four cases against the local fix. Evidence is recorded in
[`overview-provider-outage.json`](../evidence/overview-provider-outage.json).
Browser console resource errors for a genuine provider 429 should be reported
separately from uncaught JavaScript errors; a provider outage is an expected degraded
state, not a successful source observation.

Verification for this change: full pytest **107 passed, 23 skipped** in 100.74s;
workbench API **14 passed**; Node UI **6 passed**; browser outage regression
**4 passed**; Ruff, Bandit, and JavaScript syntax checks passed. Optional local
PostgreSQL, container, and Spark integrations were not enabled for this frontend
change. The evidence records these skips explicitly.
