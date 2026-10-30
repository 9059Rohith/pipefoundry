def test_console_escapes_receipts_and_has_only_read_only_controls():
    from pipefoundry.console import render_console

    html = render_console(
        {
            "pipeline": {
                "name": '<script>alert("x")</script>',
                "revision": 7,
                "status": "succeeded",
                "schedule": "0 0 * * *",
            },
            "workload": {"rows": 13, "invalid_rows": 0},
            "backfill": [{"date": "2026-01-10"}, {"date": "2026-01-11"}],
            "events": [
                {
                    "action": "rollback",
                    "revision": 7,
                    "outcome": "succeeded",
                    "created": "2026-10-30T12:00:00+00:00",
                }
            ],
            "artifact": {"sha256": "a" * 64, "storage": "PostgreSQL BYTEA"},
            "observed_at": "2026-10-30T12:00:01+00:00",
        }
    )
    assert "&lt;script&gt;" in html
    assert "<script>" not in html and "<form" not in html
    assert ">13<" in html and ">7<" in html
    for destination in (
        'href="/demo"',
        'href="/health/ready"',
        "github.com/9059Rohith/pipefoundry",
    ):
        assert destination in html


def test_pending_console_never_fabricates_execution_counts():
    from pipefoundry.console import render_console

    html = render_console(None)
    assert "Waiting for verified" in html
    assert 'http-equiv="refresh"' in html
    assert "Rows per run" not in html and "succeeded" not in html
