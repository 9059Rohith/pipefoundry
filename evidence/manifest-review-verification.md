# Manifest security auditor verification

Feature code: `2c2a073` (pushed to main). Production Ready was confirmed by Vercel
CLI inspection on 2026-11-02 for deployment `dpl_7EfrPK2qGWiGm1oPzsFzpZ9Wrran`.
Canonical route: https://pipefoundry.vercel.app/workbench/review

- TDD red: 12 new Python cases failed before implementation; new JS review renderer
  test failed before the helper existed.
- Full Python suite: **100 passed, 23 skipped** in 171.33 seconds. Environment-gated
  PostgreSQL/container/Spark integration tests were not enabled.
- Expanded final review suite: **17 passed**, adding exact field regressions for
  concurrency, start deadlines, Job runtime deadlines, seccomp and new policy findings.
- JavaScript: **6 tests passed**; `node --check` passed for both browser scripts.
- Ruff: clean for source, tests and both new scripts. Bandit: no findings.
- Locked production dependency audit: 24 packages, no known vulnerabilities;
  see `manifest-review-dependency-audit.json`.
- Wheel package built successfully with the new review module and browser assets.
- Bounded 30-sample local pure-function benchmark: p50 **11.6642 ms**, p95 **17.4414 ms**,
  p99 **17.953 ms**; 493-byte typed request / 28,406-byte two-version evidence output.
  These are local static-review timings, not hosted latency or throughput claims.
- Canonical production smoke: review HTML/assets 200; real audit/diff 200 with
  **10 passing controls, 1 mutable-image warning, 0 failures, 1 N/A**. Two requested
  resource increases generated two capacity risk escalations.
- The production JSON evidence hash was independently recomputed from compact,
  sorted UTF-8 JSON and matched. Unsafe unknown fields returned 422 without the
  secret marker; oversized input returned 413. Private apply/agent routes returned 401.
- **0 model requests, 0 cluster actions.** No secrets, AI configuration, counters,
  public-agent limits, private release controls, dependencies or runtime image changed.

The review explicitly does not claim cluster admission or full PSS certification.
Both baseline and candidate configs are rendered by the current server at revision 1;
the comparison is not a live cluster drift check. Export hashes are content fingerprints,
not signatures or release approvals.

Reproduce with `pytest -q`, `pytest tests/test_manifest_review.py -q`,
`node --test tests/ui.test.cjs`, `ruff check src tests scripts/benchmark_review.py
scripts/smoke_manifest_review.py`, `bandit -r src -q`,
`python scripts/benchmark_review.py --samples 30`, and
`python scripts/smoke_manifest_review.py`.
