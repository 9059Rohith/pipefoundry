# Operations and recovery

## Review before deployment

Use `pipefoundry plan CONFIG > release.json` and `pipefoundry apply release.json
--idempotency-key KEY` for a guarded release. Sentinel binds reviewed intent to
exact state, source/operator/artifact identities, expiry and budgets. Read
`pipefoundry receipt KEY` after a request timeout rather than creating another
key. See [Release Sentinel](release-sentinel.md) for the full recovery protocol.
The following `preview` workflow remains available as an advisory comparison.

Run `pipefoundry --state-dir PATH preview CONFIG --executor local` (or
`kubernetes`) before deploying. The API equivalent is authenticated
`POST /deployments/preview` with `{config, executor}`, the same envelope used by
`POST /pipelines`. Inspect `action`, `current.revision`, `current.status`,
`operation_in_progress`, fingerprints and changed field paths. Invalid API
configuration returns a sanitized 422; use CLI `validate CONFIG` in a protected
terminal when field-specific diagnostics are needed.

Preview does not reserve a revision, acquire/release locks, restore files, write
audit records or affect schedules. First opening an unused local state directory
initializes its metadata database. A matching failed/rendered/torn-down revision
still reports update. An active operation must be investigated before a mutation;
preview can report its presence without bypassing it. A no-op means the desired
specification matches successful/deployed metadata; it does not prove live cluster
agreement or include changed administrator image, namespace, DSN or allowlist
settings. Deploy after preview still explicitly creates and executes a revision.

For hosted PostgreSQL metadata, use a config with PostgreSQL output when previewing
local execution. The same hosted restriction applies to deploy. Rollback restores
configuration using the current operator runtime settings; inspect both the config
diff and those settings during recovery.

## Local pipeline failure

1. Run `pipefoundry status NAME`, `pipefoundry logs NAME` and
   `pipefoundry audit NAME`. A failed revision is retained.
2. Check connector allowlist, TLS CA, API status/size, source contract and database
   connectivity. Worker messages intentionally omit DSNs and driver traces.
3. Run the fixed workload directly in a controlled terminal if deeper driver
   diagnostics are needed. Avoid publishing raw environment values or DSNs.
4. Fix configuration or operator settings and deploy again. New revision IDs are
   expected. Retrying a SQL partition upserts existing IDs.

`teardown` preserves data and audit history. It stops/deletes cluster workloads;
there is no background local scheduler to stop. It does not drop PostgreSQL
tables, remove PVCs, erase local data or destroy AWS resources.

## Crash / stuck operation lock

An interrupted deploy may leave an `operations` row. Confirm no worker, kubectl
or job is still running and reconcile the actual external state first. Back up
the metadata DB and revisions together. Inspect using SQLite:

```sql
SELECT name, started FROM operations;
SELECT name, revision, status, executor FROM revisions ORDER BY name, revision;
```

For Sentinel receipts, prefer `recover-release KEY --confirm-worker-stopped`
after stopping both controller and worker. A crash before receipt reservation
can leave only an operation row: inspect receipts and actual state first.
After confirming the operation is inactive, remove only the exact observed
`(name, started)` lock with a parameterized operator script and set its unfinished revision to `failed` in the
same administrative recovery transaction. Record the recovery in the incident
log. Ordinary lifecycle and Sentinel locks are never reclaimed by age; process
death does not prove an external mutation stopped. The opt-in synthetic demo
can reclaim its own old seed operation, but that exception is disabled permanently
for a pipeline name once any Sentinel plan exists. Sentinel launch receipts do
not substitute for inspecting external effects.

## PostgreSQL

Compose requires `POSTGRES_PASSWORD` and `PIPEFOUNDRY_API_TOKEN`. For tests on a
machine with a cached image, `POSTGRES_IMAGE=postgres:17-bookworm` can override the
default image; the observed image/digest must be recorded in evidence.

Set `PIPEFOUNDRY_POSTGRES_DSN` to localhost:55435 for host tests, or service
`postgres:5432` from Compose. The production role should receive only the grants
needed for its fixed table. The sample creates the table for developer setup;
production should preapply schema migrations and remove DDL rights. Use TLS
`sslmode=verify-full` with a trusted CA outside Compose.

Quality-check failure aborts the whole current batch. Previously committed dates
remain valid. For corrupt preexisting rows, investigate and repair the source/
table rather than disabling quality checks. Back up before repair. Configuration
rollback does not undo data. Use PostgreSQL backups/PITR for data restoration.

To remove *only this project's local test services*, run `docker compose down` in
this directory with the same environment settings. Volumes remain by default.
`docker compose down -v` permanently removes project data and is an explicit
operator data-deletion decision.

## Kubernetes installation

1. Build/publish the worker image or load it into a local cluster. The ordinary
   image supports Python ingestion; Spark uses `Dockerfile.spark`.
2. Choose the namespace and storage class. The chart defaults to one API replica
   and `ReadWriteOnce` storage. Multi-node workers sharing data generally need
   RWX storage (such as EFS/NFS), node coordination, or an external data sink.
   EKS EBS/EFS CSI installation and storage classes are operator prerequisites;
   Terraform does not silently install them. SQLite on shared network filesystems
   is unsuitable for multiple concurrent writers.
3. Provision API and connector secrets without exposing values in shell history.
   Example secret file: a protected file containing only the API token, supplied
   to `kubectl create secret generic pipefoundry-api --from-file=token=PATH`.
4. `helm upgrade --install pipefoundry infra/helm/pipefoundry --namespace pipefoundry --create-namespace`
5. Inspect `kubectl -n pipefoundry rollout status deployment/pipefoundry-api`.
   Readiness fails if token configuration is missing. Configure TLS ingress with
   the chart's allowed ingress namespace. NetworkPolicy blocks all other ingress.
6. Configure connector egress CIDRs and PostgreSQL pod labels/namespace rules.
   Policies require actual enforcement; test a forbidden connection on-cluster.
7. Deploy the generated CronJob using the trusted host CLI. If using its generated
   Helm chart instead, supply the namespace with Helm; do not also deploy the
   same pipeline through another scheduler.

Cluster mutations need namespaced permission for ConfigMaps, CronJobs and Jobs;
read operations also need pod listing/log access. Worker pods need none. Do not
grant cluster-admin to the API. Terraform's operator administrator role is for
cluster bootstrap, not the runtime service identity.

A failed multi-object apply may leave a newer ConfigMap and an older active
CronJob. Inspect actual cluster state before retry/rollback/teardown; the latest
failed metadata revision does not mean older scheduled workloads stopped.

`status` queries the live CronJob after deployment, and reports last schedule/
success timestamps and active job count. `logs` reads bounded pod logs through
kubectl. Connectivity errors return an error rather than presenting stale
metadata as current. Pending jobs commonly indicate image pull, PVC scheduling,
resource, secret or egress-policy issues. Inspect Jobs/Pods/events with kubectl.

Backfill creates a date-specific Job from the current revision's pod spec and
waits for completion. Same revision/date has a deterministic name: retry an
already-completed date observes that job; delete a failed job only after reviewing
its logs before retry. Coordinate manual jobs with normal schedules; CronJob
`Forbid` does not lock manually created Jobs. Backfill aborts on the first failed
partition and retains earlier successful partitions. Teardown removes only
objects labelled for that pipeline; it retains the shared PVC and API chart.

Inspect `cluster_targets` independently of the latest artifact's executor/status.
The registry records original namespaces before apply, including possibly partial
failed applies. Rendering a new revision or switching to local execution leaves
those targets intact. Teardown visits all recorded namespaces, clears only targets
whose deletion succeeded, and fails if any deletion fails. Retrying completes
the remaining targets. A changed `PIPEFOUNDRY_NAMESPACE` does not change cleanup
of previously recorded targets. The target's `last_attempted_revision` is an
attempt receipt, not evidence that its CronJob completed or even fully applied.

## Terraform / optional cloud delivery

Run `terraform fmt -check -recursive`, `terraform init -backend=false` and
`terraform validate` before planning. Copy the backend configuration into a
protected operator environment; use encrypted remote state with locking. Supply
an existing administrator role ARN, review region/AZs and check EKS version support
before `plan`. No AWS credentials were supplied for portfolio verification.

The EKS endpoint is private-only. Use VPN, SSM or a VPC-connected runner. The
optional manually dispatched OIDC workflow assumes a repository-restricted IAM
role on a self-hosted runner labelled `eks-vpc`; configure GitHub's `production`
environment protections. It deploys an existing cluster/chart and does not
implicitly create Terraform infrastructure. Default pushes/PRs never deploy.

Before destroying a real cluster, export data and audit backups, remove dependent
load balancers/PVCs according to retention policies, inspect a saved destroy plan,
and account for KMS deletion windows and retained log/storage resources. EKS,
two NAT gateways, two initial nodes, disks and logs generate charges until removed.

## Incident evidence

Preserve revision checksums, metadata backup, audit event IDs, UTC timestamps,
worker exit status and sanitized Kubernetes events. Never attach .env, DSNs,
tokens, Terraform state or ephemeral TLS test keys to an issue. Dependency scan
findings should be fixed and rerun; if an upstream fix is unavailable, document
the exact advisory, reachable code path and temporary mitigation rather than
silencing the scanner globally.
