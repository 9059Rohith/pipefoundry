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
| `/workbench/agent` | Limited public Gemini demo with real GitHub tool traces; no sign-in |

`/` and `/workbench` open Overview. The repository picker accepts public GitHub `owner/repository` names and persists the choice for the current tab session. No private GitHub token is attached. Results are cached for sixty seconds, with bounded page sizes and explicit API rate-limit or unavailable states.

When GitHub returns a rate limit, the workbench can use genuine previously fetched public evidence for up to 24 hours. The original `observed_at` is preserved; the response and agent trace carry `stale: true`, the model must explain the freshness limit, and the UI displays a warning plus **Cached · stale (GitHub rate limit)** beside the source. Evidence older than 24 hours is rejected. Other repositories need evidence already observed in the current process. The default repository additionally has an actual anonymous HTTP-200 metadata capture bundled for cold starts, with its source, observation time and [capture hash](../evidence/github-cache-seed.json). This is historical evidence, not a claim about current source counts. No private GitHub credential is added, and the fallback does not require database access.

The rate-limit fix passed **80 tests, 23 optional skips in 54.41 seconds**; its targeted suite passed **13 tests**, including fresh/stale cache handling and rejection after expiry. Ruff, formatting, JavaScript syntax, Bandit and wheel packaging passed. The built wheel was inspected to confirm the genuine JSON capture is included.

After promotion, the actual browser workflow succeeded with Gemini `gemini-3.5-flash-lite`: the answer identified `main` and Python, cited the repository, stated the observation time and fresh-cache status, and displayed the real `inspect_github(repository)` trace. The API token field cleared automatically. [Browser screenshot](../evidence/gemini-browser.png), [browser text](../evidence/gemini-browser.txt). A final independent hosted API request also returned HTTP 200 with a nonempty answer and actual live GitHub evidence: [final hosted JSON proof](../evidence/gemini-final-hosted-verification.json). The final runtime deployment is `dpl_Eb2bCiZpSEVTXWVQ9293zUqgz4ya` on the existing public hostname. Temporary local provider/token copies were removed after verification; production secrets remain server-side.

Pipeline configuration starts as a clearly labeled, unexecuted starter. Save edits before opening validation. The server validates with the same Pydantic model as the executor and renders with the existing Kubernetes object renderer. It performs no deployment, metadata mutation or worker invocation. Downloads are real client-generated JSON/YAML files. Drafts and activity live in sessionStorage; export them for durable copies.

Deployment previews require an authorized `PIPEFOUNDRY_API_TOKEN`. This token is used for one request and cleared from the form. The preview compares recorded state; it is not a live drift audit or release reservation. Public pages expose no execution permissions. Historical synthetic demo receipts are now authenticated at `/demo` and `/demo/console`.

The default agent page calls `POST /workbench/api/demo-agent` anonymously. Its server-side scope is fixed to `9059Rohith/pipefoundry`, preferred model `gemini-3.5-flash-lite`, a 600-character question and at most 600 output tokens per model response. The only model fallback is the fixed `gemini-3.1-flash-lite`, on the first eligible retry after a transient provider 5xx before any assistant response, including when a network retry preceded that 5xx. The chosen model remains fixed for the rest of that conversation and the response/UI reports the model actually used. Repository and model overrides are rejected. The existing `POST /workbench/api/agent` operator endpoint still requires an API token and does not enable automatic model fallback. Production uses server-only `GEMINI_API_KEY`; the dedicated Google project has billing disabled and is subject to free-tier quota. Gemini requests go to the fixed Google OpenAI-compatible Chat Completions endpoint; complete assistant/tool-call objects, including opaque thought signatures, are preserved for the next turn as required by [Google's compatibility protocol](https://ai.google.dev/gemini-api/docs/openai). Signatures are not published in the trace or verification artifacts.

On 2026-11-05, Google's [standard API pricing](https://ai.google.dev/gemini-api/docs/pricing) lists free text input/output for both models, and its [3.1 Flash-Lite model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite) marks that model stable with function calling supported. The free-only deployment depends on keeping the dedicated project's billing disabled: model names alone do not prevent charges on a billing-enabled project. Fallback uses the same server key, project and endpoint, requests no Google Search/Maps or paid hosted tools, and never switches providers. Free-tier model availability and quotas can still cause failure. Historical live 3.5 failures remain evidence; automated fallback tests do not establish a successful live 3.1 response.

## Public demo safety and allowances

The public route uses fixed time buckets persisted in the existing metadata PostgreSQL database: 3 accepted attempts per visitor per 600 seconds, 2 shared attempts per 60 seconds and 30 shared attempts per 86,400 seconds. One PostgreSQL advisory transaction lock makes all three checks and increments atomic across workers. Quota rejection returns 429 plus `Retry-After` before any provider request. An accepted attempt consumes its allowance even if the provider later fails. The UI shows these limits and a cooldown. Missing or unavailable storage returns 503 before inference; Vercel never falls back to process memory or ephemeral SQLite. Explicit local SQLite storage is available only for tests/development outside Vercel.

Visitor identifiers are HMAC-SHA256 hashes keyed by the existing server API token. The limiter stores only the hash, bucket time and count, never a raw IP address. `x-forwarded-for` is accepted only when `VERCEL=1` and the complete header is one valid IP address; otherwise the socket peer is used. Untrusted forwarding headers cannot rotate identities outside Vercel. Explicit cross-origin requests are rejected unless their origin exactly matches the request origin or the canonical HTTPS origin. Non-browser requests without an Origin header are permitted within the same quotas. Public integration status discloses only the limiter backend and identity-source mode, never addresses, hashes or credentials.

The original private pipeline/release APIs remain authenticated. This public demo grants no deployment, execution, rollback, private log or private audit permissions. Public evidence may be genuinely cached with its original observation time and explicit stale labels.

The public-demo change passed **88 tests, 23 optional skips in 249.46 seconds**, including **21 targeted tests** for the public endpoint and existing agent protocol. Concurrent SQLite connections and fresh limiter instances verified atomic shared buckets and persistence; separate checks cover client/day quotas, invalid input, spoofed forwarding headers, HMAC-only storage, origin rejection, and database errors stopping inference. Ruff, formatting, JavaScript syntax, Bandit and wheel packaging passed. The real Vercel runtime confirmed PostgreSQL storage and Vercel-overwritten forwarded-IP mode, then returned an actual anonymous HTTP 200 with a Gemini answer and a GitHub tool trace: [first anonymous proof](../evidence/public-ai-first-anonymous.json). This first request used no operator credentials.

The independent browser workflow then returned a real Gemini answer with repository branch/language, source URL, observation time and an `inspect_github(repository)` trace. There was no token field and no console warnings/errors: [public browser screenshot](../evidence/public-demo-browser.png), [browser text](../evidence/public-demo-browser.txt). A third anonymous request in the same minute was rejected by the persistent allowance with **429 and `Retry-After: 7`**, before inference: [quota rejection](../evidence/public-ai-quota-rejection.json). The final public runtime is `dpl_GF9sHtAgdwzkzdsBXuP4ZwY9FBLY`, promoted to the existing canonical hostname. [QA summary](../evidence/public-demo-qa-summary.json). No temporary credential copies were created for these anonymous checks.

The loop requires actual GitHub evidence before returning an answer and allows only `inspect_github`, at most three model steps and four tool calls. Gemini shares a monotonic 60-second scheduling deadline, six-provider-request ceiling and two-retry allowance across the whole conversation, including model fallback. Each synchronous HTTP timeout is capped to the remaining deadline and 25 seconds; socket phase timeouts do not forcibly cancel all work at exactly 60 seconds. Backoff is one then two seconds. A 429 may receive one retry within that shared allowance; any quota response prevents model fallback. Network errors can retry but do not themselves trigger a model switch. A valid `Retry-After` longer than the bounded wait is returned without retrying early or switching models. The UI respects numeric/date cooldowns on 429/503 and never automatically resubmits. Persistent quota exhaustion returns an explicit 429 with no paid fallback. The agent cannot run shell commands, deploy, dispatch workflows or mutate the control plane. Provider output and repository evidence remain escaped text. Missing credentials produce an explicit 503. Operators who explicitly select `PIPEFOUNDRY_AI_PROVIDER=openai` can still use `OPENAI_API_KEY` and the existing Responses adapter; Gemini never falls back to it automatically.

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
