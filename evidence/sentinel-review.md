# Release Sentinel review and decisions

The parent agent independently reviewed the complete releases module, engine lease/materialization/schema, metadata adapter and API integration. It found no material blocker in atomic receipt/revision reservation, lease retention through execution, recovery/terminal receipt serialization, immutable authenticated plan identity or runtime/artifact-driven no-op eligibility. Final full installed Python 3.15/PostgreSQL verification passed after the additional demo guard.

Two additional findings were handled before completion:

- Partial local rendering could leave checksum files without committed metadata, preventing a replacement plan. A real render interruption regression failed, then passed after failed/incomplete snapshots were allowed to bind partial bytes. Successful/deployed snapshots still require full manifest integrity.
- Existing synthetic-demo age-based recovery could delete a protected release lease, including the gap before receipt reservation. A real PostgreSQL regression failed, then passed after automatic reclamation was disabled for every name with an immutable Sentinel plan. Legacy demo recovery tests still pass.

Decisions: infer the operation when omitted but freeze the resolved operation into policy; conservatively use 10000 input rows for dynamic sources; retain at-most-once launch reservation rather than automatically repeating uncertain effects; require trusted operator confirmation after stopping controller/worker; manually inspect and clear only an exact orphaned operation owner if no receipt was ever reserved. The consequences and legacy API bypass are documented in the README, runbook and threat model. No deferred material findings remain.
