# Concept prompts

Both concepts used the built-in image generation tool, not a CLI/API fallback. These are the final brief sets used before coding; all interactive product surfaces are implemented as native HTML/CSS/JavaScript rather than image screenshots.

## Primary editor

Create a premium production web application UI concept screenshot for PipeFoundry, a real data-pipeline developer workbench. Full desktop primary screen, approximately 1600 × 1100, no browser frame or marketing hero. Graphite/obsidian software with warm orange `#ff8d43`, base `#101214`, surfaces `#181b1e`, separators `#30363c`, near-white `#edf1f4`, muted `#9aa5ae`. Readable 14–16px chrome, 32px headings, 15px/24px monospace editor. No neon, gradients, emoji, avatars or fake metrics. Thin-line icons, purposeful framed workspaces, 8px radii.

Include the whole sidebar and existing information architecture: Overview, Repository, Workflows, Executions, Releases, Commit history; Build & validate: Pipeline editor, Validation, Manifests, Deployment plans, Foundry agent; Governance: Security policy, Session audit, Integrations. Select Pipeline editor. Topbar Workspace / Pipeline editor with command search and Ctrl K, Source link. Main title Pipeline editor; subtitle Compose typed configuration. Validate before execution. Connected navigable rail: 01 Configure, 02 Validate, 03 Manifests, 04 Plan. Highlight current Configure without claiming other steps completed.

Wide editor at roughly 68%, configuration inspector at 32%. Editor toolbar pipeline.json / Draft, Format JSON, Save draft, orange Validate configuration. Readable line numbers and JSON property coloring. Exact starter: name orders-hourly; schedule `0 * * * *`; fixture input orders.json; transform normalize_orders; SQLite output orders.db; CPU 250 millicores; memory 256 MiB. Editor status JSON / UTF-8 / Session draft / Not executed. Inspector shows Fixture → Normalize orders → SQLite, actual draft fields, and neutral Not validated yet / Run validation to inspect this draft. Export JSON and Load starter. Bottom Validation results strip: results appear after real server validation. No synthetic success, executions or public deployment controls.

Saved concept: [editor](../evidence/design-concept-editor.png).

## Agent and evidence

Create a complete Foundry agent screen in the same graphite/orange workbench system and full information architecture. Select Foundry agent. Keep the same header, command search, thin-line icons, spacing and type rhythm. Main heading Foundry agent; subtitle Ask about this public repository. Inspect the evidence. No sign-in required.

Two aligned workspaces: question panel around 45%, analysis panel 55%. Question: Inspect repository metadata. State its default branch and primary language with source URL and observation time. Fixed read-only repository 9059Rohith/pipefoundry; orange Ask Foundry action. No API-token/key field. Clear allowance rows: 3 requests / 10 minutes per visitor; shared 2 / minute and 30 / day; no deployment permissions, dated cached evidence may be used.

Use a clearly dated previously recorded actual example only to establish answer/evidence typography: main branch, Python, GitHub repository source; observed 2026-11-01 19:09:41 UTC. Show a note that a dated repository observation is not a current deployment check. Sources and tool evidence table: inspect_github / repository / observation time / actual API source. No fabricated counts, runs or charts. The actual product starts with empty analysis until a real provider request completes; the historical concept answer is not seeded into the application.

Saved concept: [agent](../evidence/design-concept-agent.png).
