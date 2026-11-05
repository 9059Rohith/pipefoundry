"""The public artwork inventory. Names are constants rather than filesystem input."""

PAGE_ARTWORK = {
    "overview": ("pipe-manifold", "Pipeline manifold"),
    "repository": ("source-stack", "Source repository"),
    "workflows": ("automation-junction", "Automation junction"),
    "runs": ("execution-raceway", "Execution raceway"),
    "run": ("run-oscillograph", "Execution trace"),
    "releases": ("artifact-rack", "Release artifact rack"),
    "commits": ("branch-engraving", "Commit branches"),
    "editor": ("configuration-die", "Configuration tooling"),
    "validation": ("schema-gate", "Schema gate"),
    "manifests": ("exploded-bundle", "Exploded manifest bundle"),
    "review": ("inspection-optics", "Manifest inspection optics"),
    "plans": ("revision-comparator", "Revision comparator"),
    "policy": ("sealed-boundary", "Execution boundary"),
    "audit": ("ledger-strips", "Audit ledger"),
    "integrations": ("connector-board", "Connector board"),
    "agent": ("evidence-receiver", "Evidence receiver"),
}

SECTION_ARTWORK = {
    "overview": (
        ("source-inlet", "Configuration chapter"),
        ("test-bench", "Validation chapter"),
        ("evidence-chain", "Review chapter"),
    ),
    "editor": (("transform-cutaway", "Connector flow inspector"),),
    "manifests": (("bundle-seal", "Rendered artifact panel"),),
    "review": (("rollback-rail", "Dated Kubernetes execution proof"),),
    "policy": (("perimeter-mesh", "Workload controls panel"),),
    "agent": (("citation-lattice", "Source evidence panel"),),
}

ARTWORK = {f"{name}.svg" for name, _ in PAGE_ARTWORK.values()} | {
    f"{name}.svg" for entries in SECTION_ARTWORK.values() for name, _ in entries
}
ARTWORK_PATHS = frozenset(f"/workbench/art/{asset}" for asset in ARTWORK)
