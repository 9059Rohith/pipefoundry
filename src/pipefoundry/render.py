"""Render concrete versioned workloads without evaluating user templates."""

import hashlib
import json
import os
from pathlib import Path

import yaml

from pipefoundry.models import Pipeline


def objects(config: Pipeline, revision: int) -> list[dict]:
    labels = {"app.kubernetes.io/name": "pipefoundry-worker", "pipeline": config.name}
    name = config.name
    image = os.environ.get("PIPEFOUNDRY_WORKER_IMAGE", "pipefoundry:0.1.0")
    # Image is operator-controlled, never accepted from a pipeline config.
    pod = {
        "metadata": {"labels": labels},
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
            "containers": [
                {
                    "name": "worker",
                    "image": image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": ["python", "-m", "pipefoundry.worker"],
                    "args": ["--config", "/config/pipeline.json", "--root", "/state"],
                    "envFrom": [
                        {"secretRef": {"name": "pipefoundry-connectors", "optional": True}}
                    ],
                    "env": [
                        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
                        {"name": "TMPDIR", "value": "/scratch"},
                        {"name": "SPARK_LOCAL_DIRS", "value": "/scratch"},
                        {"name": "JAVA_TOOL_OPTIONS", "value": "-Djava.io.tmpdir=/scratch"},
                    ],
                    "resources": {
                        "requests": {
                            "cpu": f"{config.resources.cpu_millis}m",
                            "memory": f"{config.resources.memory_mib}Mi",
                        },
                        "limits": {
                            "cpu": f"{config.resources.cpu_millis}m",
                            "memory": f"{config.resources.memory_mib}Mi",
                        },
                    },
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "volumeMounts": [
                        {"name": "config", "mountPath": "/config", "readOnly": True},
                        {"name": "state", "mountPath": "/state"},
                        {"name": "tmp", "mountPath": "/scratch"},
                    ],
                }
            ],
            "volumes": [
                {"name": "config", "configMap": {"name": f"{name}-r{revision}"}},
                {"name": "state", "persistentVolumeClaim": {"claimName": "pipefoundry-data"}},
                {"name": "tmp", "emptyDir": {"sizeLimit": "256Mi"}},
            ],
        },
    }
    cronjob = {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {"name": name, "labels": labels},
        "spec": {
            "schedule": config.schedule,
            "timeZone": "Etc/UTC",
            "concurrencyPolicy": "Forbid",
            "startingDeadlineSeconds": 120,
            "successfulJobsHistoryLimit": 2,
            "failedJobsHistoryLimit": 3,
            "jobTemplate": {
                "spec": {
                    "backoffLimit": 2,
                    "activeDeadlineSeconds": 300,
                    "ttlSecondsAfterFinished": 86400,
                    "template": pod,
                }
            },
        },
    }
    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": f"{name}-r{revision}", "labels": labels},
        "data": {"pipeline.json": config.model_dump_json(indent=2)},
    }
    return [configmap, cronjob]


def render(config: Pipeline, revision: int, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    resources = objects(config, revision)
    (directory / "pipeline.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    (directory / "cronjob.yaml").write_text(yaml.safe_dump(resources[1]), encoding="utf-8")
    (directory / "bundle.yaml").write_text(yaml.safe_dump_all(resources), encoding="utf-8")
    chart = directory / "helm"
    (chart / "templates").mkdir(parents=True)
    (chart / "Chart.yaml").write_text(
        yaml.safe_dump(
            {
                "apiVersion": "v2",
                "name": config.name,
                "version": f"0.1.{revision}",
                "appVersion": "0.1.0",
                "description": "Immutable PipeFoundry pipeline revision",
            }
        ),
        encoding="utf-8",
    )
    (chart / "values.yaml").write_text("{}\n", encoding="utf-8")
    (chart / "templates" / "workload.yaml").write_text(
        yaml.safe_dump_all(resources), encoding="utf-8"
    )
    # Airflow calls the fixed worker module, never a user-supplied command or eval.
    dag = f'''"""Generated PipeFoundry revision; targets Airflow 3.3.2 and standard provider."""
from datetime import datetime, timezone, timedelta
from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator
from pipefoundry.worker import run
from pipefoundry.models import Pipeline
import json

CONFIG = json.loads({config.model_dump_json()!r})

def execute_partition(ds, **context):
    return run(Pipeline.model_validate(CONFIG), "/opt/airflow/pipeline-state", ds)

with DAG(dag_id={config.name!r}, schedule={config.schedule!r},
         start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
         catchup=False, max_active_runs=1, default_args={{"retries": 2}}) as dag:
    PythonOperator(task_id="execute", python_callable=execute_partition,
                   execution_timeout=timedelta(minutes=5))
'''
    (directory / "airflow_dag.py").write_text(dag, encoding="utf-8")
    checksums = {
        str(path.relative_to(directory)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    (directory / "checksums.json").write_text(json.dumps(checksums, indent=2), encoding="utf-8")
    return checksums
