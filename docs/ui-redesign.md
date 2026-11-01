# Developer workbench redesign

PipeFoundry retains FastAPI and vanilla JavaScript. Fourteen navigation pages plus execution detail now share a graphite/orange design system, coherent thin-line SVG icons, a responsive navigation shell and keyboard command palette. The design was generated before implementation: [primary editor concept](../evidence/design-concept-editor.png), [agent/evidence concept](../evidence/design-concept-agent.png). Native concept dimensions are 1513 × 1039. [Tokens and component decisions](design-system.md).

## Working flows

- **Configure → Validate → Manifests → Plan:** readable numbered/syntax-highlighted editor; Format JSON; save/export a session draft; real inline server validation; errors and configuration fingerprint; manifest copy/download; authenticated metadata-only plan preview. Continuing the journey preserves the editor draft. Edits invalidate the prior validation display. JSON primitives/arrays are rejected before saving.
- **Inspect repository activity:** actual GitHub metadata, workflow definitions, executions and steps, releases, assets and commits. Larger table text, scoped filters and read-only record dialogs expose the returned records without fabricating activity. Historical cached evidence retains its observation time and stale warning.
- **Navigate:** Ctrl/Cmd+K searches existing pages and available editor actions; Ctrl/Cmd+S saves a draft; Ctrl/Cmd+Shift+Enter validates it. Native dialogs support Escape and focus restoration. Mobile navigation provides a close button, focus containment and return focus.
- **Read AI evidence:** the existing anonymous Gemini endpoint and persistent PostgreSQL allowances are unchanged. A small tested renderer formats headings, lists, inline code and guarded GitHub citations while escaping raw HTML. Source records remain separately inspectable. No example answer is preloaded.
- **Review governance:** generated workload policy, actual tab-session audit and live integration configuration keep their existing boundaries. Operator tokens remain confined to the protected plan workflow.

## Verification

- Python full suite: **88 passed, 23 optional integration skips in 97.32 seconds**. Those skips retain the previously documented PostgreSQL/Spark/container coverage; Docker was not restarted for this UI change.
- Targeted agent/public-boundary tests: **21 passed**.
- `node --test tests/ui.test.cjs`: **5 passed**. Covers unsafe Markdown/HTML and citation URLs, JSON escaping/highlighting, command search and non-object draft rejection.
- Ruff, formatting, Bandit, JavaScript syntax and wheel packaging passed. The wheel includes the new UI helper and genuine GitHub metadata cache. No runtime dependency was added.
- Canonical HTTPS checks verified all 15 page routes, security headers, deployed asset hashes, actual validation and private write rejection (401), without an AI request. [Machine-readable smoke evidence](../evidence/premium-ui-public-smoke.json).
- Root Browser/CUA local review verified desktop editor geometry, actual validation acceptance and SHA, rendered ConfigMap/CronJob, the protected plan boundary, and 390px mobile navigation. Mobile document/client widths were both 375px: no horizontal document overflow. No console warnings/errors were observed in that flow.
- Canonical production Browser/CUA review repeated real editor validation, inspected the actual rendered CronJob with non-root execution and resource caps, retained the protected plan boundary, and navigated through the command palette by keyboard. All 14 navigation views were opened and their actual headings checked; each document's scroll width equaled its client width. Commit filtering reduced the real returned records to the `2ca446` commit, and the record dialog exposed its details and source. [Production editor](../evidence/premium-editor-desktop.jpg).
- One anonymous production Gemini call returned an actual `inspect_github` repository trace, `main` / `Python`, the source URL and live observation time `2026-11-01T20:30:34.251235+00:00`. The answer explicitly explained that repository metadata does not prove a workload was deployed. [Actual agent result](../evidence/premium-agent-live.jpg). No additional AI call was made for this documentation.
- Download YAML saved the actual 2,995-byte `orders-hourly-bundle.yaml` through the production browser. Independent shell parsing verified ConfigMap and CronJob documents, `runAsNonRoot: true`, and matching CPU/memory requests and limits of `250m` / `256Mi`. Download SHA-256: `8cf9f849d7a81db4259f8d972bd1e5565523957006c29323a83260a2f5aacae2`.
- Production mobile review at 390px verified the editor, 375px document/client widths, and menu close/return focus. [Production mobile editor](../evidence/premium-editor-mobile-live.jpg). The final production browser tab reported no console errors or warnings.
- Copy YAML displayed "Kubernetes bundle copied to the clipboard." after the browser's write promise resolved. The Browser/CUA clipboard read-back did not confirm its contents; clipboard content transfer is therefore not recorded as independently verified. Rejected clipboard access presents the download alternative. [Browser QA record](../evidence/premium-ui-browser-qa.json).

## Fidelity ledger

| Area | Reference and verified outcome |
| --- | --- |
| Geometry | Connected numbered journey, wide editor and narrower configuration inspector follow the primary concept. The 1280px browser review uses the intended responsive gutter/sidebar adaptation. |
| Palette | Flat graphite surfaces, fine gray separators, near-white text and one warm orange action color match the selected system; no decorative glow or gradients. |
| Typography | 34px desktop heading, 14px/24px monospace editor, larger body/control type and aligned line numbers were inspected in the browser. |
| Navigation/icons | All existing page labels remain; emoji/letter wordmarks were replaced by a coherent SVG pipe mark and thin-line icons. |
| Workflow | Format/save/real validation/artifact/plan controls use the actual existing API. A validation result appears only after server acceptance. |
| Mobile | The navigation collapses to a focus-managed menu; the editor and inspector stack, and data tables/code scroll inside their own containers. |
| Evidence | Agent formatting escapes untrusted HTML and rejects non-GitHub/credential-bearing citation destinations. Source observations are dated; no synthetic executions or live-status claims were added. |

Intentional copy adaptations: command search says pages/actions rather than claiming a file search; the footer emphasizes evidence rather than implying public deployment permissions; actual agent output starts empty instead of reproducing the concept's recorded example. These preserve the implemented scope. The primary concept's pipe mark is used consistently rather than switching to the alternate mark in the agent concept.

The current public UI runtime is `dpl_83guHtdMks8cVpohdY8wb5MFmZru` on [the canonical workbench](https://rohith-pipefoundry.vercel.app). These checks describe concrete behavior and design comparison; they do not establish a ranking or perfect score.
