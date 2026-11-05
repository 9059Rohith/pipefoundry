# PipeFoundry blueprint artwork

All 24 plates are original project artwork drawn from independent vector compositions in
`scripts/build_blueprints.py`. PipeFoundry has permission to use them in the site.
They contain no licensed stock or third-party artwork. The shared geometry helpers provide
consistent drafting marks, colors and edges. Each plate has its own tooling composition.

Every file is a self-contained, responsive SVG with a 760 × 340 view box. Route plates load
at the page entrance. Section plates load lazily and reserve their dimensions before download.
The images are decorative and use empty alt text. No information or controls depend on them.

| File | Placement | Composition | Bytes |
| --- | --- | --- | ---: |
| `pipe-manifold.svg` | `/workbench/overview` masthead | Pipeline manifold | 10,816 |
| `source-stack.svg` | `/workbench/repository` masthead | Source repository | 6,560 |
| `automation-junction.svg` | `/workbench/workflows` masthead | Automation junction | 10,055 |
| `execution-raceway.svg` | `/workbench/runs` masthead | Execution raceway | 5,264 |
| `run-oscillograph.svg` | `/workbench/run` masthead | Execution trace | 7,209 |
| `artifact-rack.svg` | `/workbench/releases` masthead | Release artifact rack | 5,247 |
| `branch-engraving.svg` | `/workbench/commits` masthead | Commit branches | 3,372 |
| `configuration-die.svg` | `/workbench/editor` masthead | Configuration tooling | 4,773 |
| `schema-gate.svg` | `/workbench/validation` masthead | Schema gate | 4,817 |
| `exploded-bundle.svg` | `/workbench/manifests` masthead | Exploded manifest bundle | 6,846 |
| `inspection-optics.svg` | `/workbench/review` masthead | Manifest inspection optics | 5,122 |
| `revision-comparator.svg` | `/workbench/plans` masthead | Revision comparator | 7,283 |
| `sealed-boundary.svg` | `/workbench/policy` masthead | Execution boundary | 2,810 |
| `ledger-strips.svg` | `/workbench/audit` masthead | Audit ledger | 3,350 |
| `connector-board.svg` | `/workbench/integrations` masthead | Connector board | 8,243 |
| `evidence-receiver.svg` | `/workbench/agent` masthead | Evidence receiver | 3,262 |
| `source-inlet.svg` | `/workbench/overview` · Configuration chapter | Configuration chapter | 4,624 |
| `test-bench.svg` | `/workbench/overview` · Validation chapter | Validation chapter | 4,270 |
| `evidence-chain.svg` | `/workbench/overview` · Review chapter | Review chapter | 8,827 |
| `transform-cutaway.svg` | `/workbench/editor` · Connector flow inspector | Connector flow inspector | 5,322 |
| `bundle-seal.svg` | `/workbench/manifests` · Rendered artifact panel | Rendered artifact panel | 4,408 |
| `rollback-rail.svg` | `/workbench/review` · Dated Kubernetes execution proof | Dated Kubernetes execution proof | 5,793 |
| `perimeter-mesh.svg` | `/workbench/policy` · Workload controls panel | Workload controls panel | 4,468 |
| `citation-lattice.svg` | `/workbench/agent` · Source evidence panel | Source evidence panel | 4,958 |

**24 distinct SVGs, 137,699 bytes total.**
The median page loads one image before its working surface. The public artwork
route admits only the explicit inventory and sends an image-only content type.
