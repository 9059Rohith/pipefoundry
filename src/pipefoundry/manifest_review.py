"""Deterministic static review of server-rendered objects. No cluster or model calls."""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

import yaml

from pipefoundry.models import Pipeline, StrictModel
from pipefoundry.render import objects

DOCS = {
    "security": "https://kubernetes.io/docs/concepts/security/pod-security-standards/",
    "images": "https://kubernetes.io/docs/concepts/containers/images/",
    "resources": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
    "cronjob": "https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/",
    "job": "https://kubernetes.io/docs/concepts/workloads/controllers/job/",
    "deployment": "https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#progress-deadline-seconds",
    "dry_run": "https://kubernetes.io/docs/reference/using-api/api-concepts/#dry-run",
}


class ReviewRequest(StrictModel):
    config: Pipeline
    baseline: Pipeline | None = None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def quantity(value, resource):
    """Parse the resource units emitted by our renderer; fail closed on unknown units."""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(m|Ki|Mi|Gi)?", str(value))
    if not match:
        return None
    suffix = match[2] or ""
    factors = (
        {"": 1, "m": Decimal("0.001")}
        if resource == "cpu"
        else {
            "": 1,
            "Ki": 1024,
            "Mi": 1024**2,
            "Gi": 1024**3,
        }
    )
    if suffix not in factors:
        return None
    try:
        return Decimal(match[1]) * factors[suffix]
    except InvalidOperation:
        return None


def audit_objects(bundle):
    """Evaluate object fields, never YAML text, annotations, or substring matches."""
    pods, jobs, crons, deployments = [], [], [], []
    for obj in bundle:
        root = f"{obj['kind']}/{obj['metadata']['name']}"
        spec = obj.get("spec", {})
        if obj["kind"] == "CronJob":
            crons.append((root, spec))
            job = spec["jobTemplate"]["spec"]
            jobs.append((root + ".spec.jobTemplate", job))
            pods.append((root + ".spec.jobTemplate.spec.template.spec", job["template"]["spec"]))
        elif obj["kind"] in {"Job", "Deployment"}:
            (jobs if obj["kind"] == "Job" else deployments).append((root, spec))
            pods.append((root + ".spec.template.spec", spec["template"]["spec"]))
    if not pods or any(not p.get("containers") for _, p in pods):
        raise ValueError("No supported workload containers to review")
    containers = []
    for path, pod in pods:
        for kind in ("containers", "initContainers", "ephemeralContainers"):
            for index, container in enumerate(pod.get(kind, [])):
                containers.append((f"{path}.{kind}[{index}]", container, pod))
    checks = []

    def check(key, title, entries, explain, remedy, source="security", warning=False):
        evidence = [{"path": p, "value": v, "passed": bool(ok)} for p, v, ok in entries]
        state = (
            "na"
            if not evidence
            else ("pass" if all(e["passed"] for e in evidence) else "warn" if warning else "fail")
        )
        checks.append(
            {
                "id": key,
                "title": title,
                "status": state,
                "explanation": explain,
                "remediation": remedy,
                "source": DOCS[source],
                "evidence": evidence,
            }
        )

    entries = []
    for path, c, pod in containers:
        inherited = {**pod.get("securityContext", {}), **c.get("securityContext", {})}
        nonroot = inherited.get("runAsNonRoot")
        uid = inherited.get("runAsUser")
        entries.append(
            (
                path + ".effectiveSecurityContext",
                {
                    "runAsNonRoot": nonroot,
                    "runAsUser": uid,
                },
                nonroot is True and uid != 0,
            )
        )
    check(
        "non-root",
        "Run containers as non-root",
        entries,
        "Container overrides take precedence over pod defaults. "
        "A root UID conflicts with non-root execution.",
        "Set runAsNonRoot: true and use a nonzero image or explicit user.",
    )
    check(
        "privilege-escalation",
        "Block privilege escalation",
        [
            (
                path + ".securityContext",
                c.get("securityContext", {}),
                c.get("securityContext", {}).get("allowPrivilegeEscalation") is False
                and c.get("securityContext", {}).get("privileged", False) is False,
            )
            for path, c, _ in containers
        ],
        "Each container must explicitly disable privilege escalation and must not be privileged.",
        "Set allowPrivilegeEscalation: false; remove privileged mode.",
    )
    check(
        "capabilities",
        "Drop Linux capabilities",
        [
            (
                path + ".securityContext.capabilities",
                c.get("securityContext", {}).get("capabilities"),
                "ALL" in c.get("securityContext", {}).get("capabilities", {}).get("drop", [])
                and not c.get("securityContext", {}).get("capabilities", {}).get("add", []),
            )
            for path, c, _ in containers
        ],
        "This project policy drops ALL capabilities and permits no additions.",
        "Set capabilities.drop: [ALL] and remove added capabilities.",
    )
    check(
        "read-only-root",
        "Keep the root filesystem read-only",
        [
            (
                path + ".securityContext.readOnlyRootFilesystem",
                c.get("securityContext", {}).get("readOnlyRootFilesystem"),
                c.get("securityContext", {}).get("readOnlyRootFilesystem") is True,
            )
            for path, c, _ in containers
        ],
        "A read-only root reduces writable container surface; "
        "mounted scratch/state volumes remain writable.",
        "Set readOnlyRootFilesystem: true and mount only required writable volumes.",
    )
    entries = []
    for path, c, pod in containers:
        profile = c.get("securityContext", {}).get(
            "seccompProfile", pod.get("securityContext", {}).get("seccompProfile", {})
        )
        entries.append(
            (
                path + ".effectiveSeccompProfile",
                profile,
                profile.get("type") in {"RuntimeDefault", "Localhost"},
            )
        )
    check(
        "seccomp",
        "Use a restricted seccomp profile",
        entries,
        "The effective container or pod profile must be RuntimeDefault or Localhost.",
        "Set seccompProfile.type: RuntimeDefault; verify any Localhost profile exists on nodes.",
    )
    check(
        "service-account",
        "Disable service-account token mount",
        [
            (
                path + ".automountServiceAccountToken",
                pod.get("automountServiceAccountToken"),
                pod.get("automountServiceAccountToken") is False,
            )
            for path, pod in pods
        ],
        "Worker pods do not need Kubernetes API credentials. "
        "An omitted field can inherit token mounting.",
        "Set pod automountServiceAccountToken: false.",
    )
    check(
        "image-digest",
        "Pin immutable image content",
        [
            (
                path + ".image",
                c.get("image"),
                bool(re.fullmatch(r"[^\s@]+@sha256:[0-9a-fA-F]{64}", c.get("image", ""))),
            )
            for path, c, _ in containers
        ],
        "Tags can point to different content later. "
        "Digest pinning improves release reproducibility.",
        "The operator should set PIPEFOUNDRY_WORKER_IMAGE to a trusted image@sha256:digest.",
        "images",
        warning=True,
    )
    entries = []
    for path, c, _ in containers:
        resources = c.get("resources", {})
        valid = True
        for resource in ("cpu", "memory"):
            requested = quantity(resources.get("requests", {}).get(resource), resource)
            limit = quantity(resources.get("limits", {}).get(resource), resource)
            valid &= requested is not None and limit is not None and 0 < requested <= limit
        entries.append((path + ".resources", resources, valid))
    check(
        "resources",
        "Bound CPU and memory",
        entries,
        "Both resources need positive requests and limits, with requests no larger than limits.",
        "Specify positive CPU/memory requests and limits; review capacity with your operator.",
        "resources",
    )
    check(
        "job-deadline",
        "Bound Job execution time",
        [
            (
                path + ".spec.activeDeadlineSeconds",
                job.get("activeDeadlineSeconds"),
                type(job.get("activeDeadlineSeconds")) is int
                and 0 < job["activeDeadlineSeconds"] <= 3600,
            )
            for path, job in jobs
        ],
        "Project policy caps Job active deadlines at one hour. The renderer uses five minutes.",
        "Set a positive activeDeadlineSeconds no greater than 3600.",
        "job",
    )
    check(
        "concurrency",
        "Prevent overlapping scheduled Jobs",
        [
            (
                path + ".spec.concurrencyPolicy",
                cron.get("concurrencyPolicy"),
                cron.get("concurrencyPolicy") == "Forbid",
            )
            for path, cron in crons
        ],
        "Forbid avoids overlap within the same CronJob; "
        "separate CronJobs can still run concurrently.",
        "Set concurrencyPolicy: Forbid and verify application idempotency.",
        "cronjob",
    )
    check(
        "start-deadline",
        "Bound missed scheduled starts",
        [
            (
                path + ".spec.startingDeadlineSeconds",
                cron.get("startingDeadlineSeconds"),
                type(cron.get("startingDeadlineSeconds")) is int
                and 10 <= cron["startingDeadlineSeconds"] <= 3600,
            )
            for path, cron in crons
        ],
        "Project policy allows 10–3600 seconds to avoid an unbounded catch-up window.",
        "Set startingDeadlineSeconds between 10 and 3600.",
        "cronjob",
    )
    check(
        "deployment-progress",
        "Deployment progress deadline",
        [
            (
                path + ".spec.progressDeadlineSeconds",
                dep.get("progressDeadlineSeconds"),
                type(dep.get("progressDeadlineSeconds")) is int
                and dep["progressDeadlineSeconds"] > dep.get("minReadySeconds", 0),
            )
            for path, dep in deployments
        ],
        "Applies only to Deployments. PipeFoundry currently renders CronJobs, "
        "so this is not applicable.",
        "For Deployments, set a progress deadline greater than minReadySeconds.",
        "deployment",
    )
    return checks


def snapshot(config):
    bundle = objects(config, 1)
    checks = audit_objects(bundle)
    manifest = yaml.safe_dump_all(bundle, sort_keys=False)
    return {
        "config": config.model_dump(),
        "config_sha256": fingerprint(config.model_dump()),
        "objects": bundle,
        "manifest": manifest,
        "manifest_sha256": fingerprint(bundle),
        "yaml_sha256": hashlib.sha256(manifest.encode()).hexdigest(),
        "checks": checks,
        "summary": {
            s: sum(c["status"] == s for c in checks) for s in ("pass", "warn", "fail", "na")
        },
    }


def flatten(value, path=""):
    if isinstance(value, dict):
        return {
            k: v
            for key in sorted(value)
            for k, v in flatten(value[key], f"{path}.{key}" if path else key).items()
        }
    if isinstance(value, list):
        return {
            k: v
            for index, item in enumerate(value)
            for k, v in flatten(item, f"{path}[{index}]").items()
        }
    return {path: value}


def changes(before, after):
    old, new = flatten(before), flatten(after)
    return [
        {"path": path, "before": old.get(path), "after": new.get(path)}
        for path in sorted(old.keys() | new.keys())
        if path not in old or path not in new or old[path] != new[path]
    ]


def compare(baseline, current):
    config_changes = changes(baseline["config"], current["config"])
    for change in config_changes:
        resource = change["path"].startswith("resources.")
        change["risk"] = (
            ("escalation" if change["after"] > change["before"] else "availability")
            if resource
            else "review"
        )
        change["reason"] = {
            "escalation": "Higher per-pod resource budget requires a capacity review.",
            "availability": "Lower resource budget may throttle CPU or cause memory exhaustion.",
            "review": "Schedule, identity or data-flow changed; verify intended release behavior.",
        }[change["risk"]]
    prior = {c["id"]: c["status"] for c in baseline["checks"]}
    rank = dict(na=0, warn=1, fail=2)
    rank["pass"] = 0
    new_findings = [
        c["id"] for c in current["checks"] if rank[c["status"]] > rank[prior.get(c["id"], "na")]
    ]
    manifest_changes = changes(baseline["objects"], current["objects"])
    return {
        "changed": bool(config_changes or manifest_changes),
        "config_changes": config_changes,
        "manifest_changes": manifest_changes,
        "new_findings": new_findings,
        "escalations": sum(c["risk"] == "escalation" for c in config_changes) + len(new_findings),
        "scope": "Both configs rendered on this server at revision 1; not live cluster drift.",
    }


def review(body: ReviewRequest):
    current = snapshot(body.config)
    baseline = snapshot(body.baseline) if body.baseline else None
    evidence = {
        "schema": "pipefoundry.release-review.v1",
        "policy_version": "2026-11-02.1",
        "method": "static structured manifest inspection",
        "cluster_validation": "not performed",
        "limitations": [
            "Selected project controls only; not a full Pod Security Standards certification.",
            "Cluster admission, RBAC, quota, image provenance and runtime are not checked.",
            "Hashes detect changed evidence; they are not signatures or deployment approvals.",
        ],
        "current": current,
        "baseline": baseline,
        "comparison": compare(baseline, current) if baseline else None,
        "sources": DOCS,
    }
    return {
        "evidence": evidence,
        "evidence_sha256": fingerprint(evidence),
        "hash_encoding": "SHA-256: UTF-8 JSON, sorted keys, no whitespace, ensure_ascii=false",
    }
