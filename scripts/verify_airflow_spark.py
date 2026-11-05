"""Run a rendered PipeFoundry Airflow DAG over a public NYC fare extract."""

import argparse
import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess  # nosec B404
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

from pipefoundry.models import Pipeline
from pipefoundry.render import render


def digest(data):
    return hashlib.sha256(data).hexdigest()


def source_rows(data, metadata):
    if (
        not metadata["source_url"].startswith(
            "https://data.cityofnewyork.us/resource/4b4i-vvec.json?"
        )
        or digest(data) != metadata["sha256"]
    ):
        raise ValueError("Public source identity differs from the capture metadata")
    records = json.loads(data)
    rows = {}
    for record in records:
        cents = Decimal(record["fare_amount"]) * 100
        row_id = digest(record["row_id"].encode())
        if not cents.is_finite() or cents != cents.to_integral_value() or row_id in rows:
            raise ValueError("Public source contains a fractional cent or duplicate identity")
        rows[row_id] = int(cents)
    if len(rows) != metadata["rows"] or sum(rows.values()) != metadata["total_fare_cents"]:
        raise ValueError("Public source totals differ from the capture metadata")
    return rows


def verify_output(output, expected):
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.master("local[2]")
        .appName("pipefoundry-airflow-readback")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .getOrCreate()
    )
    try:
        rows = sorted(
            (row.id, row.amount_cents, row.currency)
            for row in spark.read.parquet(str(output))
            .select("id", "amount_cents", "currency")
            .collect()
        )
        if rows != sorted((row_id, cents, "USD") for row_id, cents in expected.items()):
            raise ValueError("Spark readback differs from the exact public source mapping")
        files = sorted(output.glob("currency=USD/*.gz.parquet"))
        if not files:
            raise ValueError("Gzip Parquet files are missing from the USD partition")
        return {
            "rows": len(rows),
            "distinct_ids": len({row[0] for row in rows}),
            "fare_total_cents": sum(row[1] for row in rows),
            "currency": "USD",
            "canonical_rows_sha256": digest(json.dumps(rows, separators=(",", ":")).encode()),
            "files": [
                {
                    "path": str(file.relative_to(output)),
                    "size_bytes": file.stat().st_size,
                    "sha256": digest(file.read_bytes()),
                }
                for file in files
            ],
        }
    finally:
        spark.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-metadata", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    data = args.source.read_bytes()
    metadata = json.loads(args.source_metadata.read_text(encoding="utf-8"))
    expected = source_rows(data, metadata)
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    state = work / "state"
    (state / "data").mkdir(parents=True)
    normalized = (
        "\n".join(
            json.dumps({"id": row_id, "amount_cents": cents, "currency": "USD"})
            for row_id, cents in expected.items()
        )
        + "\n"
    )
    (state / "data" / "fares.json").write_text(normalized, encoding="utf-8")
    config = Pipeline.model_validate(
        {
            "name": "nyc-fares-proof",
            "schedule": "0 2 * * *",
            "input": {"connector": "spark_json", "path": "fares.json"},
            "output": {"connector": "parquet", "path": "fares-parquet"},
            "resources": {"cpu_millis": 1000, "memory_mib": 2048},
        }
    )
    checksums = render(config, 1, work / "revision")
    dag_file = work / "revision" / "airflow_dag.py"
    os.environ["AIRFLOW_HOME"] = str(work / "airflow")
    os.environ["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
    os.environ["AIRFLOW__CORE__DAGS_FOLDER"] = str(work / "revision")
    package_source = str(Path(__file__).resolve().parents[1] / "src")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        filter(None, [package_source, os.environ.get("PYTHONPATH", "")])
    )
    os.environ["PIPEFOUNDRY_AIRFLOW_STATE_DIR"] = str(state)
    os.environ["SPARK_LOCAL_IP"] = "127.0.0.1"
    subprocess.run(  # nosec B603
        [sys.executable, "-m", "airflow", "db", "migrate"], check=True, timeout=90
    )
    spec = importlib.util.spec_from_file_location("pipefoundry_verified_dag", dag_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    logical_date = datetime.now(UTC)
    started = time.perf_counter()
    dagrun = module.dag.test(logical_date=logical_date)
    elapsed = time.perf_counter() - started
    with sqlite3.connect(f"file:{work / 'airflow' / 'airflow.db'}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        task = db.execute(
            "SELECT task_id,state,try_number,start_date,end_date FROM task_instance "
            "WHERE dag_id=? AND run_id=?",
            (dagrun.dag_id, dagrun.run_id),
        ).fetchone()
    if dagrun.state != "success" or task is None or task["state"] != "success":
        raise RuntimeError("Airflow did not mark the DAG and execute task successful")
    started = time.perf_counter()
    output = verify_output(
        state / "data" / "fares-parquet" / logical_date.date().isoformat(), expected
    )
    report = {
        "source": metadata,
        "mapping": "SHA-256 source row ID, exact meter fare cents, USD",
        "normalized_jsonl_sha256": digest(normalized.encode()),
        "airflow_version": version("apache-airflow"),
        "standard_provider_version": version("apache-airflow-providers-standard"),
        "spark_version": __import__("pyspark").__version__,
        "python_version": sys.version.split()[0],
        "execution_mode": "Airflow DAG.test local execution",
        "dag": {
            "id": dagrun.dag_id,
            "run_id": dagrun.run_id,
            "state": dagrun.state,
            "task": dict(task),
            "logical_date": logical_date.isoformat(),
            "generated_file_sha256": checksums["airflow_dag.py"],
            "duration_seconds": round(elapsed, 3),
        },
        "independent_spark_readback_seconds": round(time.perf_counter() - started, 3),
        "parquet": output,
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
