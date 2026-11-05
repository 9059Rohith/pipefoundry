import importlib.util
import json
import sys
from pathlib import Path

import pytest


def gate_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_gate.py"
    assert path.is_file(), "build gate must exist before a release can produce a receipt"
    spec = importlib.util.spec_from_file_location("build_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture_project(tmp_path, body):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text(body)
    (tmp_path / "requirements.lock").write_text("example==1.0\n")
    return tmp_path / "receipt.json"


def pytest_command():
    return [[sys.executable, "-m", "pytest", "-q", "--junitxml=results.xml"]]


def test_failed_tests_delete_stale_success_receipt(tmp_path):
    output = fixture_project(tmp_path, "def test_failure():\n    assert False\n")
    output.write_text('{"status":"passed"}')
    with pytest.raises(RuntimeError, match="failed"):
        gate_module().run_gate(tmp_path, output, pytest_command())
    assert not output.exists()


def test_receipt_counts_real_pass_and_skip_and_tracks_input_changes(tmp_path):
    output = fixture_project(
        tmp_path,
        "import pytest\ndef test_pass():\n    assert True\n"
        '@pytest.mark.skip(reason="requires PostgreSQL")\ndef test_skip():\n    pass\n',
    )
    gate = gate_module()
    gate.run_gate(tmp_path, output, pytest_command())
    receipt = json.loads(output.read_text())
    assert receipt["pytest"] == {"tests": 2, "passed": 1, "failures": 0, "errors": 0, "skipped": 1}
    assert receipt["skips"] == [{"reason": "requires PostgreSQL", "count": 1}]
    assert receipt["status"] == "passed"
    original = receipt["fingerprints"]
    (tmp_path / "src" / "app.py").write_text("value = 2\n")
    (tmp_path / "requirements.lock").write_text("example==2.0\n")
    gate.run_gate(tmp_path, output, pytest_command())
    changed = json.loads(output.read_text())["fingerprints"]
    assert changed["source"] != original["source"]
    assert changed["locks"] != original["locks"]
    assert changed["tests"] == original["tests"]


@pytest.mark.parametrize(
    "cases",
    [
        '<testcase name="failure"><failure /></testcase>',
        '<testcase name="error"><error /></testcase>',
        '<testcase name="skip"><skipped /></testcase>',
        "",
    ],
)
def test_success_exit_cannot_forge_success_with_invalid_junit_results(tmp_path, cases):
    output = fixture_project(tmp_path, "")
    xml = f"<testsuites><testsuite>{cases}</testsuite></testsuites>"
    command = [
        sys.executable,
        "-c",
        f"from pathlib import Path; Path('results.xml').write_text({xml!r})",
    ]
    with pytest.raises(RuntimeError, match="JUnit"):
        gate_module().run_gate(tmp_path, output, [command])
    assert not output.exists()


def test_success_exit_requires_junit_and_nonempty_tests(tmp_path):
    output = fixture_project(tmp_path, "")
    with pytest.raises(RuntimeError, match="JUnit"):
        gate_module().run_gate(tmp_path, output, [[sys.executable, "-c", "pass"]])
    assert not output.exists()
