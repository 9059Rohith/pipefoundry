# PipeFoundry visual audit

The live [PipeFoundry workbench](https://rohith-pipefoundry.vercel.app) is a
functional data pipeline application. The repository is `9059Rohith/pipefoundry`.
The existing Vercel project serves the Python 3.12+ FastAPI container from the
locked dependencies and wheel. The interface uses server-rendered HTML and
vanilla JavaScript and CSS. Production already exposes both established aliases.

| Surface | Current behavior | Visual opportunity |
| --- | --- | --- |
| Overview and repository | Public GitHub metadata with observation times and cache labeling | Give the build journey a strong opening and show evidence as a separate destination |
| Workflows, executions, execution detail, releases, and commits | Repository inspection, filterable tables, dialogs and source links | Give each view recognizable artwork while keeping labels, filters and rows compact |
| Editor, validation and manifests | Typed JSON editor, server validation, configuration hash and actual YAML copy/download | Distinguish configuration, inspection and artifact steps visually |
| Deployment plans and release review | Protected plan comparison, public static manifest review, evidence export and dated real Kubernetes run proof | Keep the review action easy to reach and separate rendered evidence from local execution |
| Policy, audit and integrations | Workload boundaries, browser-session audit and actual connection status | Create a calm governance family with its own illustrations and readable contrast |
| Foundry agent | Quota-limited Gemini for this repository, source and dated tool evidence | Reserve artwork for headings and explanatory panels to keep the form and result legible |

The 16 workbench pages use one template, an exact public route allowlist and
same-origin Content Security Policy. The deployment, private agent and release
mutation APIs require a server-validated bearer token. Hosted metadata and
rate limits use PostgreSQL. Operator-supplied tokens for protected comparisons
remain in the browser only for the request. There are no payments or public
account registration flows.

The original interface has a keyboard command palette, mobile menu, focus
states, a reduced-motion override, and meaningful loading and error states.
Its flat graphite shell and repeated panels make the route purposes harder to
distinguish at a glance. It ships no workbench background illustrations.
Navigation and motion have few cues to connect the build stages. The redesign
will retain the workbench's established hierarchy, apply a warm graphite,
copper and teal blueprint system, and add original artwork at each route
entrance and selected sections. Editorial motion belongs to overview; dense
tools should stay steady during work.

Acceptance requires visible distinct artwork on every route, at least 20
unique placed files, mobile/tablet/desktop checks, reduced-motion verification,
and the actual editor → validation → manifest → review workflow. Private API
guards, anonymous AI limits, and the dated Kubernetes evidence must still be
verifiable after deployment. Public artwork should remain exact-allowlisted
and the initial viewport should request only the artwork it needs.
