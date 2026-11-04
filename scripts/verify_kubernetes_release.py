"""Run a guarded release and rollback on an owned, disposable local Kubernetes cluster."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404
import tempfile
import time
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import yaml

from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline
from pipefoundry.releases import ReleaseSentinel, digest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://data.cityofnewyork.us/resource/4b4i-vvec.json"
QUERY = {
    "$select": ":id as row_id,tpep_pickup_datetime,fare_amount",
    "$where": (
        "tpep_pickup_datetime >= '2023-01-01T00:00:00' "
        "and tpep_pickup_datetime < '2023-01-01T00:02:00' and fare_amount > 0"
    ),
    "$order": "tpep_pickup_datetime, :id",
    "$limit": 12,
}
NODE_IMAGE = (
    "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"
)
K3S_IMAGE = (
    "rancher/k3s:v1.34.1-k3s1@sha256:"
    "5e0707cfd1239b358ef73f3254bc3eadc027dd30cd5ec6ca41e29e47652a1b8c"
)
REGISTRY_IMAGE = (
    "registry:3@sha256:d4032d4cc323c1731c707931ecada07a53076eac38e3b61ae57533f170f2c6c3"
)
WORKER_BASE = (
    "python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f"
)
WORKER_DOCKERFILE = f"""FROM {WORKER_BASE}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
COPY requirements.lock .
RUN python -m pip install --no-cache-dir --only-binary=:all: -r requirements.lock
COPY src ./src
USER 10001:10001
"""
NAMESPACE = "pipefoundry-proof"
PIPELINE = "nyc-taxi-fares"
SOURCE_HOST = f"fare-source.{NAMESPACE}.svc"
PARTITION = "2023-01-01"
SOURCE_SERVER = """
import ssl
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

server = ThreadingHTTPServer(("0.0.0.0", 8443), SimpleHTTPRequestHandler)
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain("/tls/cert.pem", "/tls/key.pem")
server.socket = tls.wrap_socket(server.socket, server_side=True)
server.serve_forever()
"""
READ_SINK = """
import json, sqlite3, sys
with sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True) as db:
    print(json.dumps(db.execute(
        "SELECT partition_date,id,amount_cents,currency FROM orders ORDER BY partition_date,id"
    ).fetchall()))
"""


def command(*args, stdin=None, timeout=60, show=False):
    result = subprocess.run(  # nosec B603
        args,
        input=stdin,
        text=True,
        encoding="utf-8",
        capture_output=not show,
        check=True,
        timeout=timeout,
        errors="replace",
    )
    return (result.stdout or "").strip()


def observed_source():
    with httpx.stream("GET", SOURCE, params=QUERY, timeout=30) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > 65536:
                raise RuntimeError("Public source exceeded the sample byte limit")
        observed = datetime.now(UTC).isoformat()
    raw_rows = json.loads(body)
    rows = []
    for row in raw_rows:
        cents = Decimal(row["fare_amount"]) * 100
        if cents != cents.to_integral_value():
            raise ValueError("Public fare is not exactly representable in cents")
        rows.append(
            {
                "id": hashlib.sha256(row["row_id"].encode()).hexdigest(),
                "amount_cents": int(cents),
                "currency": "USD",
            }
        )
    if len(rows) != QUERY["$limit"] or len({row["id"] for row in rows}) != len(rows):
        raise RuntimeError("Public source returned an incomplete or duplicate sample")
    return rows, {
        "dataset": "NYC Open Data 2023 Yellow Taxi Trip Data",
        "url": SOURCE,
        "query": QUERY,
        "observed_at": observed,
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "source_rows": raw_rows,
        "mapped_rows_sha256": digest(rows),
        "row_mapping": "SHA-256 of Socrata row ID, exact fare_amount × 100, USD",
    }


def pod(name, image, args, mounts, volumes, *, working_dir=None, port=None):
    container = {
        "name": name,
        "image": image,
        "args": args,
        "command": ["python"],
        "volumeMounts": mounts,
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        },
    }
    if working_dir:
        container["workingDir"] = working_dir
    if port:
        container["readinessProbe"] = {"tcpSocket": {"port": port}}
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "labels": {"app": name}},
        "spec": {
            "restartPolicy": "Never",
            "automountServiceAccountToken": False,
            "securityContext": {
                "runAsNonRoot": True,
                "runAsUser": 10001,
                "runAsGroup": 10001,
                "fsGroup": 10001,
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "containers": [container],
            "volumes": volumes,
        },
    }


def setup_source(kube, folder, openssl, image, rows):
    cert, key = folder / "cert.pem", folder / "key.pem"
    command(
        openssl,
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "1",
        "-keyout",
        str(key),
        "-out",
        str(cert),
        "-subj",
        f"/CN={SOURCE_HOST}",
        "-addext",
        f"subjectAltName=DNS:{SOURCE_HOST}",
    )
    kube("create", "namespace", NAMESPACE, namespace=False)
    kube(
        "create",
        "secret",
        "generic",
        "fare-tls",
        f"--from-file=cert.pem={cert}",
        f"--from-file=key.pem={key}",
    )
    kube(
        "create",
        "secret",
        "generic",
        "pipefoundry-connectors",
        f"--from-literal=PIPEFOUNDRY_ORDERS_URL=https://{SOURCE_HOST}:8443/fares.json",
        f"--from-literal=PIPEFOUNDRY_ALLOWED_HOSTS={SOURCE_HOST}:8443",
        "--from-literal=PIPEFOUNDRY_CA_BUNDLE=/state/fare-ca.pem",
    )
    resources = [
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": "pipefoundry-data"},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": "1Gi"}},
            },
        },
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "fare-source"},
            "data": {"fares.json": json.dumps(rows), "server.py": SOURCE_SERVER},
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "fare-source"},
            "spec": {"selector": {"app": "fare-source"}, "ports": [{"port": 8443}]},
        },
        pod(
            "fare-source",
            image,
            ["-B", "/source/server.py"],
            [
                {"name": "source", "mountPath": "/source", "readOnly": True},
                {"name": "tls", "mountPath": "/tls", "readOnly": True},
            ],
            [
                {"name": "source", "configMap": {"name": "fare-source"}},
                {"name": "tls", "secret": {"secretName": "fare-tls"}},
            ],
            working_dir="/source",
            port=8443,
        ),
        pod(
            "sink-reader",
            image,
            ["-B", "-c", "import time; time.sleep(1800)"],
            [
                {"name": "state", "mountPath": "/state"},
                {"name": "tls", "mountPath": "/tls", "readOnly": True},
            ],
            [
                {"name": "state", "persistentVolumeClaim": {"claimName": "pipefoundry-data"}},
                {
                    "name": "tls",
                    "secret": {
                        "secretName": "fare-tls",
                        "items": [{"key": "cert.pem", "path": "cert.pem"}],
                    },
                },
            ],
        ),
    ]
    kube(
        "create",
        "-f",
        "-",
        stdin=json.dumps({"apiVersion": "v1", "kind": "List", "items": resources}),
    )
    kube(
        "wait",
        "--for=condition=ready",
        "pod/fare-source",
        "pod/sink-reader",
        "--timeout=150s",
        timeout=160,
    )
    kube(
        "exec",
        "sink-reader",
        "--",
        "python",
        "-c",
        "from shutil import copyfile; copyfile('/tls/cert.pem', '/state/fare-ca.pem')",
    )
    return cert


def exercise(kube, folder, worker_image, source_cert, rows):
    os.environ.update(
        {
            "PIPEFOUNDRY_NAMESPACE": NAMESPACE,
            "PIPEFOUNDRY_WORKER_IMAGE": worker_image,
            "PIPEFOUNDRY_ORDERS_URL": f"https://{SOURCE_HOST}:8443/fares.json",
            "PIPEFOUNDRY_ALLOWED_HOSTS": f"{SOURCE_HOST}:8443",
            "PIPEFOUNDRY_CA_BUNDLE": str(source_cert),
        }
    )
    platform = Platform(folder / "state")
    sentinel = ReleaseSentinel(platform)
    baseline = Pipeline.model_validate(
        {
            "name": PIPELINE,
            "schedule": "0 0 29 2 *",
            "input": {"connector": "orders_api"},
            "output": {"connector": "sqlite", "path": "fares-baseline.db"},
            "resources": {"cpu_millis": 250, "memory_mib": 256},
        }
    )
    candidate = Pipeline.model_validate(
        {
            **baseline.model_dump(),
            "schedule": "15 0 29 2 *",
            "output": {"connector": "sqlite", "path": "fares-candidate.db"},
            "resources": {"cpu_millis": 500, "memory_mib": 384},
        }
    )
    steps = []
    baseline_template = None
    for revision, config in enumerate((baseline, candidate, baseline), start=1):
        action = ("release-create", "release-update", "rollback")[revision - 1]
        print(f"Verifying r{revision} {action}", flush=True)
        started = time.perf_counter()
        receipt = None
        if revision == 3:
            platform.rollback(PIPELINE, 1)
        else:
            plan = sentinel.plan(config, "kubernetes")
            key = f"kind-release-r{revision}"
            receipt = sentinel.apply(plan["plan_id"], plan["digest"], key)
            if receipt["state"] != "succeeded" or receipt["revision"] != revision:
                raise RuntimeError("Guarded release did not succeed at the expected revision")
            if sentinel.apply(plan["plan_id"], plan["digest"], key) != receipt:
                raise RuntimeError("Idempotent release retry changed the receipt")
        control_seconds = round(time.perf_counter() - started, 3)
        status = platform.status(PIPELINE, refresh=True)
        if status["status"] != "deployed" or status["revision"] != revision:
            raise RuntimeError("Revision transition was not recorded as deployed")
        live = json.loads(kube("get", "cronjob", PIPELINE, "-o", "json"))
        live_spec = live["spec"]
        live_config = json.loads(kube("get", "configmap", f"{PIPELINE}-r{revision}", "-o", "json"))
        template = live_spec["jobTemplate"]["spec"]["template"]["spec"]
        config_mount = next(volume for volume in template["volumes"] if volume["name"] == "config")
        container = template["containers"][0]
        if (
            json.loads(live_config["data"]["pipeline.json"]) != config.model_dump()
            or live_spec["schedule"] != config.schedule
            or config_mount["configMap"]["name"] != f"{PIPELINE}-r{revision}"
            or container["image"] != worker_image
            or container["resources"]["limits"]
            != {
                "cpu": f"{config.resources.cpu_millis}m",
                "memory": f"{config.resources.memory_mib}Mi",
            }
        ):
            raise RuntimeError(
                "Live CronJob or ConfigMap disagrees with expected release configuration"
            )
        if revision == 1:
            baseline_template = live_spec
        if revision == 3:
            # Revision 3 points to its own immutable ConfigMap.
            config_mount["configMap"]["name"] = f"{PIPELINE}-r1"
            if live_spec != baseline_template:
                raise RuntimeError("Rollback did not restore the baseline CronJob spec")
            config_mount["configMap"]["name"] = f"{PIPELINE}-r3"
        # A different sink partition makes the rollback write independently observable.
        partition = PARTITION if revision != 3 else "2023-01-02"
        job_started = time.perf_counter()
        platform.backfill(PIPELINE, partition, partition)
        job_seconds = round(time.perf_counter() - job_started, 3)
        job = f"{PIPELINE}-bf-{partition.replace('-', '')}-r{revision}"
        live_job = json.loads(kube("get", "job", job, "-o", "json"))
        state = live_job["status"]
        if not any(c["type"] == "Complete" and c["status"] == "True" for c in state["conditions"]):
            raise RuntimeError("Kubernetes Job has no Complete condition")
        log = json.loads(kube("logs", f"job/{job}"))
        sink = json.loads(
            kube(
                "exec",
                "sink-reader",
                "--",
                "python",
                "-c",
                READ_SINK,
                f"/state/data/{config.output.path}",
            )
        )
        partitions = (PARTITION, partition) if revision == 3 else (partition,)
        expected = sorted(
            [day, row["id"], row["amount_cents"], row["currency"]]
            for day in partitions
            for row in rows
        )
        if sink != expected or log != {
            "rows": len(rows),
            "total_rows": len(expected),
            "quality": {"invalid_rows": 0},
        }:
            raise RuntimeError(
                "Read-only SQLite query or worker result disagrees with the public sample"
            )
        steps.append(
            {
                "action": action,
                "revision": revision,
                "status": status["status"],
                "sentinel_receipt": receipt,
                "control_plane_seconds": control_seconds,
                "configuration": config.model_dump(),
                "configuration_sha256": digest(config.model_dump()),
                "cronjob_generation": live["metadata"]["generation"],
                "cronjob_uid": live["metadata"]["uid"],
                "job": {
                    "name": job,
                    "uid": live_job["metadata"]["uid"],
                    "start_time": state["startTime"],
                    "completion_time": state["completionTime"],
                    "succeeded_pods": state["succeeded"],
                    "seconds_including_apply_and_wait": job_seconds,
                    "worker_result": log,
                },
                "sqlite_sink": {
                    "partition": partition,
                    "rows": sink,
                    "rows_sha256": digest(sink),
                    "partition_fare_total_cents": sum(
                        row[2] for row in sink if row[0] == partition
                    ),
                },
            }
        )
    if len({step["cronjob_uid"] for step in steps}) != 1:
        raise RuntimeError("Release did not update the same live CronJob")
    return {
        "revisions": steps,
        "rollback_restored_baseline_cronjob_spec": True,
        "pipeline_audit": platform.audit(PIPELINE),
    }


def start_k3s(cleanup, args, folder, cluster, network, registry_host, registry):
    mirrors = folder / "registries.yaml"
    mirrors.write_text(
        json.dumps(
            {
                "mirrors": {
                    registry_host: {"endpoint": [f"http://{registry}:5000"]},
                    "docker.io": {"endpoint": ["https://mirror.gcr.io"]},
                }
            }
        ),
        encoding="utf-8",
    )
    airgap = []
    if args.k3s_images:
        archive = args.k3s_images.resolve(strict=True)
        airgap = [
            "--mount",
            f"type=bind,source={archive},"
            "target=/var/lib/rancher/k3s/agent/images/system.tar,readonly",
        ]
    command(
        "docker",
        "run",
        "-d",
        "--privileged",
        "--name",
        cluster,
        "--hostname",
        cluster,
        "--network",
        network,
        "-p",
        "127.0.0.1::6443",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/var/run",
        "--mount",
        f"type=bind,source={mirrors},target=/etc/rancher/k3s/registries.yaml,readonly",
        *airgap,
        args.node_image,
        "server",
        "--disable=traefik,servicelb,metrics-server",
        timeout=180,
    )
    cleanup.callback(command, "docker", "rm", "-f", "-v", cluster)
    deadline = time.monotonic() + 120
    while True:
        try:
            credentials = yaml.safe_load(
                command("docker", "exec", cluster, "cat", "/etc/rancher/k3s/k3s.yaml")
            )
            break
        except subprocess.CalledProcessError:
            if time.monotonic() >= deadline:
                raise RuntimeError("K3s did not produce the isolated kubeconfig") from None
            time.sleep(2)
    port = command("docker", "port", cluster, "6443/tcp").rsplit(":", 1)[1]
    credentials["clusters"][0]["cluster"]["server"] = f"https://127.0.0.1:{port}"
    credentials["contexts"][0]["name"] = cluster
    credentials["current-context"] = cluster
    kubeconfig = folder / "kubeconfig"
    kubeconfig.write_text(json.dumps(credentials), encoding="utf-8")
    kubeconfig.chmod(0o600)


def run(args, folder):
    rows, source = observed_source()
    kubeconfig = folder / "kubeconfig"
    cluster = f"pf-release-{uuid.uuid4().hex[:8]}"
    context = f"kind-{cluster}" if args.backend == "kind" else cluster
    network = f"{cluster}-net"
    registry = f"{cluster}-registry"
    local_image = f"{cluster}:worker"
    os.environ.pop("DOCKER_HOST", None)
    os.environ.pop("DOCKER_TLS_VERIFY", None)
    os.environ.pop("DOCKER_CERT_PATH", None)
    os.environ["DOCKER_CONTEXT"] = args.docker_context
    for key in list(os.environ):
        if key.startswith("PIPEFOUNDRY_") or key == "KUBERNETES_SERVICE_HOST":
            del os.environ[key]
    os.environ.update(
        {
            "KUBECONFIG": str(kubeconfig),
            "KIND_EXPERIMENTAL_PROVIDER": "docker",
            "KIND_EXPERIMENTAL_DOCKER_NETWORK": network,
        }
    )
    endpoint = json.loads(command("docker", "context", "inspect", args.docker_context))
    if not endpoint[0]["Endpoints"]["docker"]["Host"].startswith(("npipe://", "unix://")):
        raise RuntimeError("Select a local Docker daemon context")
    if command("docker", "info", "--format", "{{.OSType}}") != "linux":
        raise RuntimeError("Docker must be running Linux containers")

    def kube(*argv, namespace=True, **options):
        prefix = ["kubectl", "--kubeconfig", str(kubeconfig), "--context", context]
        if namespace:
            prefix += ["-n", NAMESPACE]
        return command(*prefix, *argv, **options)

    with ExitStack() as cleanup:
        print(f"Building worker for isolated cluster {cluster}", flush=True)
        command(
            "docker",
            "build",
            "-f",
            "-",
            "-t",
            local_image,
            str(ROOT),
            stdin=WORKER_DOCKERFILE,
            timeout=900,
            show=True,
        )
        cleanup.callback(command, "docker", "image", "rm", local_image)
        command("docker", "network", "create", network)
        cleanup.callback(command, "docker", "network", "rm", network)
        command(
            "docker",
            "run",
            "-d",
            "--name",
            registry,
            "--network",
            network,
            "-p",
            "127.0.0.1::5000",
            REGISTRY_IMAGE,
            timeout=180,
        )
        cleanup.callback(command, "docker", "rm", "-f", "-v", registry)
        port = command("docker", "port", registry, "5000/tcp").rsplit(":", 1)[1]
        registry_host = f"localhost:{port}"
        registry_image = f"{registry_host}/pipefoundry:proof"
        command("docker", "tag", local_image, registry_image)
        cleanup.callback(command, "docker", "image", "rm", registry_image)
        output = command("docker", "push", registry_image, timeout=300)
        manifest_digest = re.search(r"digest: (sha256:[0-9a-f]{64})", output)
        if not manifest_digest:
            raise RuntimeError("Local registry did not return a manifest digest")
        worker_image = f"{registry_host}/pipefoundry@{manifest_digest.group(1)}"
        if args.backend == "kind":
            cleanup.callback(
                command,
                args.kind,
                "delete",
                "cluster",
                "--name",
                cluster,
                "--kubeconfig",
                str(kubeconfig),
                timeout=90,
                show=True,
            )
            command(
                args.kind,
                "create",
                "cluster",
                "--name",
                cluster,
                "--image",
                args.node_image,
                "--kubeconfig",
                str(kubeconfig),
                "--wait",
                "180s",
                timeout=600,
                show=True,
            )
            node = command(args.kind, "get", "nodes", "--name", cluster)
            if node != f"{cluster}-control-plane":
                raise RuntimeError("Unexpected kind node")
            cert_dir = f"/etc/containerd/certs.d/{registry_host}"
            command("docker", "exec", node, "mkdir", "-p", cert_dir)
            command(
                "docker",
                "exec",
                "-i",
                node,
                "cp",
                "/dev/stdin",
                f"{cert_dir}/hosts.toml",
                stdin=f'[host."http://{registry}:5000"]\n',
            )
        else:
            start_k3s(cleanup, args, folder, cluster, network, registry_host, registry)
        contexts = command(
            "kubectl", "--kubeconfig", str(kubeconfig), "config", "get-contexts", "-o", "name"
        )
        current = command("kubectl", "--kubeconfig", str(kubeconfig), "config", "current-context")
        if contexts != context or current != context:
            raise RuntimeError("Isolated kubeconfig does not select exactly the owned cluster")
        if args.backend == "k3s":
            kube(
                "wait",
                "--for=create",
                f"node/{cluster}",
                "--timeout=240s",
                namespace=False,
                timeout=250,
            )
            kube(
                "wait",
                "--for=condition=ready",
                "nodes",
                "--all",
                "--timeout=240s",
                namespace=False,
                timeout=250,
            )
            for deployment in ("coredns", "local-path-provisioner"):
                kube(
                    "-n",
                    "kube-system",
                    "wait",
                    "--for=create",
                    f"deployment/{deployment}",
                    "--timeout=240s",
                    namespace=False,
                    timeout=250,
                )
            kube(
                "-n",
                "kube-system",
                "rollout",
                "status",
                "deployment/coredns",
                "--timeout=300s",
                namespace=False,
                timeout=310,
            )
            kube(
                "-n",
                "kube-system",
                "rollout",
                "status",
                "deployment/local-path-provisioner",
                "--timeout=300s",
                namespace=False,
                timeout=310,
            )
        versions = json.loads(kube("version", "-o", "json", namespace=False))
        source_cert = setup_source(kube, folder, args.openssl, worker_image, rows)
        evidence = exercise(kube, folder, worker_image, source_cert, rows)
        evidence.update(
            {
                "scope": "Executed on a disposable local Kubernetes cluster.",
                "verified_at": datetime.now(UTC).isoformat(),
                "source": source,
                "cluster_backend": args.backend,
                "kind": command(args.kind, "version") if args.backend == "kind" else None,
                "kubernetes": versions["serverVersion"]["gitVersion"],
                "kubectl": versions["clientVersion"]["gitVersion"],
                "worker_image": worker_image,
                "worker_base": WORKER_BASE,
                "node_image": args.node_image,
                "source_commit": command("git", "-C", str(ROOT), "rev-parse", "HEAD"),
            }
        )
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", default="kind")
    parser.add_argument("--backend", choices=["kind", "k3s"], default="kind")
    parser.add_argument("--docker-context", required=True)
    parser.add_argument("--node-image")
    parser.add_argument("--k3s-images", type=Path)
    parser.add_argument("--openssl", default=shutil.which("openssl") or "openssl")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pinned = NODE_IMAGE if args.backend == "kind" else K3S_IMAGE
    args.node_image = args.node_image or pinned
    if args.node_image.rsplit("@", 1)[-1] != pinned.rsplit("@", 1)[-1]:
        parser.error("--node-image must use the pinned backend image digest")
    with tempfile.TemporaryDirectory(prefix="pipefoundry-kind-") as folder:
        evidence = run(args, Path(folder))
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(f"Verified three Kubernetes revisions, Jobs and sink results in {args.output}")


if __name__ == "__main__":
    main()
