# Manifest security review — design and implementation plan

The public workbench gains a Release review page between validation and artifact export.
It accepts only the existing typed Pipeline JSON schema, renders the real ConfigMap and
CronJob on the server, and inspects the resulting object tree. It never runs kubectl,
executes workloads, consumes AI quota, or claims cluster admission.

1. Add failing tests for rendered security checks, strict/redacted public inputs,
   deterministic before/after risk comparison, and independently verifiable export hashes.
2. Implement a pure structured policy evaluator and versioned evidence envelope. Inspect
   every workload/container, including inherited pod security settings, token automount,
   immutable image digests, requests/limits, Job deadlines and CronJob concurrency.
3. Compare two validated configurations and both rendered bundles. Report ordered leaf
   changes, resource increases and decreases, identity/sink changes, and newly failing rules.
4. Connect editor, manifest view, navigation, command palette and build journey to a
   graphite/orange review workspace. Users can capture a baseline, edit a candidate,
   import a baseline JSON config, filter checks, and export the exact evidence and YAML.
5. Run all Python tests, JS tests/syntax, lint, security checks and a bounded review
   benchmark. Deploy the existing project, check Ready and canonical production routes.

Public input stays under the existing 32 KiB request boundary. No arbitrary YAML is
accepted (including aliases/anchors); unknown config fields and unsafe paths fail closed.
Review hashes are integrity fingerprints, not signatures or deployment approvals.

## Research (official sources, checked 2026-11-02)

- [Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/):
  Restricted controls motivate non-root, seccomp, capability-drop and escalation checks.
  The review is a selected static policy and does not certify full PSS compliance.
- [Deployment progress deadline](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#progress-deadline-seconds):
  applies to Deployments. This renderer emits CronJobs, so this rule is explicitly N/A.
- [CronJob](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/):
  Forbid prevents overlapping Jobs from the same CronJob; start deadlines bound missed starts.
- [Job](https://kubernetes.io/docs/concepts/workloads/controllers/job/):
  activeDeadlineSeconds bounds run duration and takes precedence over backoff retries.
- [Images](https://kubernetes.io/docs/concepts/containers/images/): digests identify immutable
  image content; mutable tags deserve a review warning even when all other checks pass.
- [Container resources](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/):
  requests guide scheduling; limits constrain runtime resource use.
- [API dry run](https://kubernetes.io/docs/reference/using-api/api-concepts/#dry-run):
  server dry run reaches API validation and admission without persistence. This public
  workbench has no cluster connection; quota, RBAC, admission and runtime remain unchecked.
