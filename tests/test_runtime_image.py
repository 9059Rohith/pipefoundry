import json
import os
import subprocess

import pytest


@pytest.mark.skipif(not os.environ.get("PIPEFOUNDRY_TEST_IMAGE"), reason="container opt in")
def test_runtime_retains_python_sql_tls_but_removes_shells_and_mount_tools():
    probe = """
import json, shutil, sqlite3, ssl, tempfile
from pathlib import Path
from pipefoundry.worker import run
from pipefoundry.models import Pipeline
result = run(Pipeline.model_validate({'name':'minimal','schedule':'0 * * * *'}),
             Path(tempfile.mkdtemp()))
print(json.dumps({'binaries':{name:shutil.which(name) for name in
    ['sh','bash','mount','umount','nsenter','perl','apt','apk','pip']},
    'rows':result['total_rows'], 'tls':ssl.OPENSSL_VERSION,
    'sqlite':sqlite3.sqlite_version}))
"""
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--network=none",
            "--tmpfs",
            "/tmp",
            os.environ["PIPEFOUNDRY_TEST_IMAGE"],
            "python",
            "-c",
            probe,
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["rows"] == 3
    assert report["tls"] and report["sqlite"]
    assert all(path is None for path in report["binaries"].values()), report
