# PipeFoundry workbench

Public URL: https://rohith-pipefoundry.vercel.app

The graphite-and-orange workbench provides fifteen routes with separate purposes:

| Route | Working capability |
| --- | --- |
| `/workbench/overview` | Live repository metadata, counts from GitHub and recent actual runs |
| `/workbench/repository` | Repository identity, language, license, branch and update metadata |
| `/workbench/workflows` | Actual Actions workflow definitions and filtered execution links |
| `/workbench/runs` | Recent GitHub runs with text and outcome filters |
| `/workbench/run?id=…` | Actual jobs and per-step outcomes for the selected run |
| `/workbench/releases` | Real release notes and asset downloads |
| `/workbench/commits` | Commit history with source links |
| `/workbench/editor` | Edit, save and export typed JSON configuration |
| `/workbench/validation` | Run the production Pipeline schema on the saved draft |
| `/workbench/manifests` | Generate and download a real Kubernetes bundle |
| `/workbench/plans` | Authenticated, metadata-only deployment comparison |
| `/workbench/policy` | Inspect generated workload security controls |
| `/workbench/audit` | Export or clear actual tab-session activity |
| `/workbench/integrations` | Inspect live server capability and credential-presence status |
| `/workbench/agent` | Real authenticated Gemini investigation with GitHub tool traces |

`/` and `/workbench` open Overview. The repository picker accepts public GitHub `owner/repository` names and persists the choice for the current tab session. No private GitHub token is attached. Results are cached for sixty seconds, with bounded page sizes and explicit API rate-limit or unavailable states.

Pipeline configuration starts as a clearly labeled, unexecuted starter. Save edits before opening validation. The server validates with the same Pydantic model as the executor and renders with the existing Kubernetes object renderer. It performs no deployment, metadata mutation or worker invocation. Downloads are real client-generated JSON/YAML files. Drafts and activity live in sessionStorage; export them for durable copies.

Deployment previews require an authorized `PIPEFOUNDRY_API_TOKEN`. This token is used for one request and cleared from the form. The preview compares recorded state; it is not a live drift audit or release reservation. Public pages expose no execution permissions. Historical synthetic demo receipts are now authenticated at `/demo` and `/demo/console`.

The agent requires an authorized API token. Production now uses server-only `GEMINI_API_KEY`, `PIPEFOUNDRY_AI_PROVIDER=gemini` and `PIPEFOUNDRY_AI_MODEL=gemini-3.5-flash-lite`. Its dedicated Google project has billing disabled and is subject to free-tier quota. Gemini requests go to the fixed Google OpenAI-compatible Chat Completions endpoint; complete assistant/tool-call objects, including opaque thought signatures, are preserved for the next turn as required by [Google's compatibility protocol](https://ai.google.dev/gemini-api/docs/openai). Signatures are not published in the trace or verification artifacts.

The loop requires actual GitHub evidence before returning an answer and allows only `inspect_github`, at most three model steps and four tool calls. Every network request has a timeout. A 429 may receive one retry per request only when the retry delay is at most two seconds; persistent quota exhaustion returns an explicit 429 with no paid fallback. The agent cannot run shell commands, deploy, dispatch workflows or mutate the control plane. Provider output and repository evidence remain escaped text. Missing credentials produce an explicit 503. Operators who explicitly select `PIPEFOUNDRY_AI_PROVIDER=openai` can still use `OPENAI_API_KEY` and the existing Responses adapter; Gemini never falls back to it automatically.

## Real Gemini verification on 2026-11-02 IST

- Actual local Gemini + GitHub HTTP loop: model `gemini-3.5-flash-lite`, one repository inspection and a grounded answer identifying the default branch and language. [Local evidence](../evidence/gemini-local-verification.json).
- Actual canonical hosted endpoint: **HTTP 200**, nonempty answer and one `inspect_github` trace citing `https://api.github.com/repos/9059Rohith/pipefoundry`. Unauthenticated calls returned **401**. [Hosted evidence](../evidence/gemini-hosted-verification.json).
- Production integration status reports Gemini, the configured model, authentication required and no fallback. Sensitive provider credentials were configured through CLI stdin and remain outside source, process arguments and browser assets.
- Full Python suite: **77 passed, 23 skipped in 110.50 seconds**. The three new Gemini regressions cover thought-signature round trips, private credential status, unsupported tools, ungrounded answer rejection and bounded quota retry. Existing OpenAI tests remain green. PostgreSQL/Spark/container opt-ins retain the previously recorded separate integration coverage; Docker was not restarted for this adapter-only change.
- Ruff check/format, JavaScript syntax and Bandit passed. No dependency was added.
- Vercel container deployment `dpl_8GcWvEuwKworUD8G2Mr15Hh1ka92` reached Ready, was checked behind deployment protection and promoted to the existing public hostname.

## Expanded integration verification on 2026-11-01

After Docker Desktop became available, the optional integration checks were rerun against two freshly created local PostgreSQL databases. No hosted database was accessed or modified. The existing local PostgreSQL container was started, and each suite received its own database created from `template0` with C locale. Credentials stayed in process memory and were never printed or committed.

| Scope | Result | Evidence |
| --- | --- | --- |
| Complete host suite with PostgreSQL and fresh minimal image enabled | **94 passed, 3 skipped in 221.67 seconds** | [Host log](../evidence/workbench-integrated-tests.txt), [JUnit](../evidence/workbench-integrated-tests.xml) |
| Installed package in Linux / Python 3.15, read-only root, UID 10001, real PostgreSQL | **92 passed, 5 skipped in 75.24 seconds** | [Runtime log](../evidence/workbench-container-tests.txt) |
| Real Linux / Java 17 / PySpark 4.0.1 JSON-to-Parquet acceptance, current source mounted read-only | **2 rows written and independently verified; 2 EUR/USD partition files** | [Spark log](../evidence/workbench-spark-tests.txt) |
| Fresh application Docker build and packaged UI assets | **Passed**, 15 page definitions and all three web assets present | [Machine-readable summary](../evidence/workbench-integration-summary.json) |

The host run enabled `PIPEFOUNDRY_POSTGRES_DSN` and `PIPEFOUNDRY_TEST_IMAGE=pipefoundry:workbench`. It covered actual PostgreSQL upserts and SQL quality, cold-root persistence, durable artifacts, locking, competing release processes, launch uniqueness, expired-operation recovery, private synthetic receipt authentication, actual HTTPS API ingestion through the worker, and the fresh minimal container's no-shell/no-package-manager execution boundary. Both PostgreSQL-only parametrized tests passed under the PostgreSQL fixture; their SQLite fixture variants are intentionally skipped. The remaining host Spark skip is covered by the separate real Linux Spark acceptance run.

The installed Linux suite used the exact fresh `/opt/venv` from the application image and current test sources. Its five skips are the two intentionally PostgreSQL-only cases under SQLite fixtures, Docker inside the test container, Spark, and the absent OpenSSL command. The host suite covers Docker and ephemeral HTTPS certificate generation; the separate Linux check covers Spark. AI credentials were unavailable during this earlier run; the subsequent real Gemini verification is recorded above.

No implementation changes were needed for these integration passes. The tested application source is commit `109d52f`; subsequent changes only update verification evidence and documentation.

## Initial desktop verification on 2026-11-01

- Full local Python suite: **74 passed, 23 skipped in 96.67 seconds**. PostgreSQL, Spark and container-dependent checks require unavailable services/opt-ins; this run does not claim those integrations passed.
- New workbench regression suite: **7 passed**. Covers every page, CSP, request bounds, no validation state mutation, authentication, no secret reflection, fixed-host GitHub transport, caching, missing AI credentials and read-only agent tool dispatch.
- Ruff check and format check: passed for all source, tests and scripts.
- `node --check src/pipefoundry/web/app.js`: passed.
- `python -m bandit -r src -q`: passed.
- `python -m pip_audit --no-deps --disable-pip -r requirements.lock --timeout 15`: no known vulnerabilities. Complete pinned runtime lock audited; [JSON report](../evidence/workbench-dependency-audit.json).
- `python -m build --wheel --no-isolation`: passed; HTML, CSS and JavaScript are included as package data.
- Built-in browser: actual draft save → validation accepted → generated YAML download. [Desktop](../evidence/workbench-desktop.png) and [mobile](../evidence/workbench-mobile.png) screenshots reviewed against the supplied design concept.
- Actual GitHub calls to repository/workflows/runs/releases/commits returned 200. The UI displayed existing failed runs honestly, without replacing outcomes.
- Vercel container deployment `dpl_CetEbYRcQ3TorjoSy4A9DYzNQfmj` reached Ready and was promoted after protected staging checks. Canonical HTTPS checks returned 200 for the workbench, actual repository inspection and valid manifest generation, and 401 for unauthenticated legacy receipts and private pipeline metadata.

Historical evidence elsewhere in the repository retains its original date and scope. This change does not establish a passing hosted CI run, a production SLA or a fresh container vulnerability scan.
