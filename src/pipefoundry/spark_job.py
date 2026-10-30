"""JSON-to-Parquet transformation; install the spark extra and Java 17+."""

from pathlib import Path


def transform(source: Path, output: Path) -> dict:
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F
    from pyspark.sql import types as T

    if source.stat().st_size > 1_048_576:
        raise ValueError("JSON input exceeds 1 MiB")
    spark = (
        SparkSession.builder.master("local[2]")
        .appName("pipefoundry")
        .config("spark.ui.enabled", "false")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    try:
        schema = T.StructType(
            [
                T.StructField("id", T.StringType(), False),
                T.StructField("amount_cents", T.LongType(), False),
                T.StructField("currency", T.StringType(), False),
            ]
        )
        frame = spark.read.schema(schema).option("mode", "FAILFAST").json(str(source))
        count = frame.count()
        if not 1 <= count <= 10_000:
            raise ValueError("Spark input requires 1 to 10000 rows")
        invalid = frame.filter(
            F.col("id").isNull()
            | ~F.col("id").rlike("^[A-Za-z0-9_-]{1,80}$")
            | F.col("amount_cents").isNull()
            | (F.col("amount_cents") < 0)
            | (F.col("amount_cents") > 1_000_000_000)
            | F.col("currency").isNull()
            | ~F.col("currency").rlike("^[A-Za-z]{3}$")
        ).count()
        if invalid:
            raise ValueError("Spark input quality check failed")
        frame = frame.withColumn("currency", F.upper("currency"))
        # Duplicate source IDs are rejected: arbitrary distributed dedup order is unsafe.
        if frame.select("id").distinct().count() != count:
            raise ValueError("Spark input contains duplicate IDs")
        # Gzip uses the JDK codec and does not extract Snappy executables into a
        # writable temp mount. This works with read-only root + noexec tmpfs.
        frame.write.mode("overwrite").option("compression", "gzip").partitionBy("currency").parquet(
            str(output)
        )
        verified = spark.read.parquet(str(output)).count()
        if verified != count:
            raise ValueError("Parquet read-after-write row count mismatch")
        return {"rows": count, "verified_rows": verified, "format": "parquet"}
    finally:
        spark.stop()
