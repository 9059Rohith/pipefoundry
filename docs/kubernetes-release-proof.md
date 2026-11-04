# Kubernetes release and rollback proof

On November 4, 2026, PipeFoundry applied two guarded revisions and rolled back to
the first configuration on a disposable, single-node Docker K3s cluster
running Kubernetes `v1.34.1+k3s1`. The hosted workbench links to this dated
run. Its interactive review analyzes the server-rendered manifests.

| Revision | Operation | Control plane | Job apply and wait | Rows written |
| --- | --- | ---: | ---: | ---: |
| 1 | Guarded create | 2.071 s | 9.837 s | 12 |
| 2 | Guarded update | 1.764 s | 7.079 s | 12 |
| 3 | Roll back to revision 1 | 1.456 s | 9.206 s | 12 |

Each revision updated the same CronJob and reached the deployed state. After
each transition the harness used PipeFoundry's backfill operation to create a
Job from that revision and waited for the Kubernetes Complete condition.
It compared every persisted SQLite record with the source mapping. Each Job
processed 12 fares totaling $289.18, with zero invalid rows. Control-plane
time includes plan, apply and the idempotent receipt retry for revisions 1 and
2. Job time includes submission and wait.

Revision 2 changed the schedule from `0 0 29 2 *` to `15 0 29 2 *`, the
resource limits from `250m / 256Mi` to `500m / 384Mi`, and the SQLite
filename from `fares-baseline.db` to `fares-candidate.db`. Revision 3
restored the baseline ConfigMap payload and entire live CronJob spec, with a
new revision-specific ConfigMap reference. A separate replay partition made
the rollback write observable. The restored baseline sink held 24 rows across
the original and replay partitions.

The harness downloaded 12 positive meter fares from NYC Open Data for a
two-minute window on January 1, 2023. It recorded the source row IDs,
timestamps, amounts and response SHA-256, then used the hashed source ID,
exact cents and USD as the typed connector records. A local TLS service
served that captured public sample to the actual worker in the cluster.
The replay partition is a storage label. The source timestamps are recorded
unchanged. [NYC Yellow Taxi Trip Data](https://data.cityofnewyork.us/Transportation/2023-Yellow-Taxi-Trip-Data/4b4i-vvec/about_data)

The measured JSON includes the Sentinel receipts, configuration hashes,
CronJob generations, Kubernetes Job UIDs and timestamps, exact SQLite rows,
and audit history. [Execution evidence](../evidence/kubernetes-release-rollback.json)

## Reproduce

Use a Linux Docker context, Python 3.12 with the repository dependencies,
kubectl compatible with Kubernetes 1.34, and OpenSSL. The harness builds a
non-root verification worker from the checked-in source and dependency lock
with a digest-pinned Python base. It creates a uniquely named cluster and
Docker network, a loopback registry and a dedicated kubeconfig. Cleanup
removes the run's cluster, network, registry, tags and temporary credentials.

```bash
python -m pip install -r requirements.lock
PYTHONPATH=src python scripts/verify_kubernetes_release.py \
  --backend k3s --docker-context default \
  --output /tmp/pipefoundry-kubernetes-proof.json
```

For a restricted network, `--node-image` accepts a local mirror reference
with the same pinned index digest. `--k3s-images` accepts a preloaded Docker
archive of the K3s system images. The measured run used the verified K3s image
via a loopback transfer and preloaded the system images during startup.
[K3s in Docker](https://docs.k3s.io/advanced#running-k3s-in-docker)
