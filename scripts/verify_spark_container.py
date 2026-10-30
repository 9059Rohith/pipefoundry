"""Real JSON-to-Parquet acceptance check on Linux + Java17, without cloud services."""

import json
import tempfile
from pathlib import Path

from pipefoundry.spark_job import transform

with tempfile.TemporaryDirectory(prefix="spark-acceptance-") as temporary:
    root = Path(temporary)
    source = root / "orders.json"
    source.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"id": "a", "amount_cents": 100, "currency": "usd"},
                {"id": "b", "amount_cents": 200, "currency": "eur"},
            ]
        )
    )
    result = transform(source, root / "parquet")
    files = list((root / "parquet").rglob("*.parquet"))
    assert result["rows"] == result["verified_rows"] == 2
    assert len(files) == 2
    print(
        json.dumps(
            {
                "result": result,
                "partition_files": sorted(str(path.relative_to(root)) for path in files),
            },
            indent=2,
        )
    )
