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
| `/workbench/agent` | Real authenticated OpenAI investigation with GitHub tool traces |

`/` and `/workbench` open Overview. The repository picker accepts public GitHub `owner/repository` names and persists the choice for the current tab session. No private GitHub token is attached. Results are cached for sixty seconds, with bounded page sizes and explicit API rate-limit or unavailable states.

Pipeline configuration starts as a clearly labeled, unexecuted starter. Save edits before opening validation. The server validates with the same Pydantic model as the executor and renders with the existing Kubernetes object renderer. It performs no deployment, metadata mutation or worker invocation. Downloads are real client-generated JSON/YAML files. Drafts and activity live in sessionStorage; export them for durable copies.

Deployment previews require an authorized `PIPEFOUNDRY_API_TOKEN`. This token is used for one request and cleared from the form. The preview compares recorded state; it is not a live drift audit or release reservation. Public pages expose no execution permissions. Historical synthetic demo receipts are now authenticated at `/demo` and `/demo/console`.

The agent requires both an authorized API token and server `OPENAI_API_KEY`. `PIPEFOUNDRY_AI_MODEL` can select a compatible Responses API model; the default is `gpt-4.1-mini`. The loop requires evidence on its first step and allows only `inspect_github`, at most three model requests and four tool calls, each with bounded network timeouts. It cannot run shell commands, deploy, dispatch workflows or mutate the control plane. Provider output and repository evidence remain escaped text. Missing credentials produce an explicit 503 and no generated answer. Live provider execution was unavailable in this session because no provider key was configured; deterministic protocol tests exercise real tool dispatch logic using isolated test transport responses.

## Verification on 2026-11-01

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
