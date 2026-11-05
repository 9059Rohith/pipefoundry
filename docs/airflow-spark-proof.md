# Airflow and Spark execution proof

On November 5, 2026, Apache Airflow 3.3.2 executed the actual generated
PipeFoundry DAG through its local `Dag.test()` runner. Its standard-provider
PythonOperator called `pipefoundry.worker.run` with the typed
`spark_json → parquet` pipeline. PySpark 4.0.1 ran with `local[2]`.
The DagRun and the `execute` task persisted success on their first attempt.

| Measured run | DAG wall time | Output |
| --- | ---: | --- |
| First generated DAG run | 34.826 s | 1,000 rows checked independently with DuckDB 2.0.0 |
| Repository harness reproduction | 34.027 s | 1,000 rows checked with a separate Spark read |
| Reproduction readback | 0.658 s | Every ID, amount and currency matched the source mapping |

Timing covers each local DAG execution and excludes dependency installation
and Airflow metadata migration. The persisted reproduction task ran from
`05:32:52.931440` to `05:33:23.405906 UTC`. Both runs used generated DAG
SHA-256 `a01a51daee906e587c637c3d7f05e361d0c86f95f874d153c8d2267344a886ec`.
[First execution and independent readback](../evidence/airflow-spark-independent.json) ·
[First persisted Airflow receipt](../evidence/airflow-spark-receipt.json) ·
[Repository harness execution](../evidence/airflow-spark-reproduction.json)

The input is a bounded capture of 1,000 positive meter fares from NYC's
published 2023 Yellow Taxi Trip Data. The capture records its request,
observation time, byte size and SHA-256. The mapping hashes the source row
identifier, converts the fare exactly to cents, and records USD. The source
contains 1,000 distinct IDs and 1,974,145 cents in total. The execution partition
uses the Airflow logical date; the source request retains its January 2023
observation window. [Public data source](https://data.cityofnewyork.us/Transportation/2023-Yellow-Taxi-Trip-Data/4b4i-vvec/about_data)

Spark wrote Gzip Parquet under `currency=USD`. Its worker checked the bounded
input, duplicate identities, field quality and read-after-write row count.
The independent readback compared every normalized tuple, including exact
integer cents. Both runs produced canonical row SHA-256
`697d3440f010098d76cbc1f333ee4e2b5aa5d57ef17dd0a73110ac66407d1f89`.
[Source capture](../evidence/airflow-spark-source.json) ·
[Capture metadata](../evidence/airflow-spark-source-metadata.json)

## Reproduce on Linux or WSL

Use Java 17+, Python 3.12, and an isolated environment. Airflow supports
installation with its versioned constraints.
[Airflow installation](https://airflow.apache.org/docs/apache-airflow/3.3.2/start.html)

```bash
uv venv .venv-airflow --python 3.12
uv pip install --python .venv-airflow/bin/python \
  apache-airflow==3.3.2 \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt
uv pip install --python .venv-airflow/bin/python \
  apache-airflow-providers-standard==1.19.0 pyspark==4.0.1 'psycopg[binary]==3.3.6'
PYTHONPATH=src .venv-airflow/bin/python scripts/verify_airflow_spark.py \
  --source evidence/airflow-spark-source.json \
  --source-metadata evidence/airflow-spark-source-metadata.json \
  --work-dir /tmp/pipefoundry-airflow-proof-1 \
  --report /tmp/pipefoundry-airflow-proof-1.json
```

Choose a fresh work directory for each run. The harness configures its own
Airflow home and DAG folder, migrates that metadata database, renders and
executes the generated DAG, checks the stored task state, and reads the actual
Parquet output. It records package versions, task timestamps, measured
durations, source identity and output file hashes.

The operator can set `PIPEFOUNDRY_AIRFLOW_STATE_DIR` for a writable worker
root. The generated DAG retains `/opt/airflow/pipeline-state` as its default.
The existing [Kubernetes release proof](kubernetes-release-proof.md) records
the separate deployed workload run and rollback.

## PostgreSQL and production release follow-up

A full Windows suite against an isolated native PostgreSQL 18.2 cluster passed 126 tests in 266.22 seconds. Four cases were skipped. Two require a durable backend and are inapplicable to their SQLite parameter variants. The container identity and Windows Spark tests are opt-in. The Linux Airflow/Spark runs above exercised the actual Spark workload separately. [Full suite output](../evidence/openfx-postgres-suite.txt) · [JUnit report](../evidence/openfx-postgres-suite-junit.xml)

Commit `8c639e6cf740ed228916ba49e1eb8d704f6f7094` was built as a production Vercel container, verified in staging, and promoted. The public manifest workflow passed evidence digest checks, bad input returned 422, oversized input returned 413, and protected execution endpoints returned 401. [Production verification](../evidence/openfx-release-verification.json)
