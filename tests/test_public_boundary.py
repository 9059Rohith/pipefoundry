import asyncio


def exchange(app, receive, authorization=None, headers=None):
    events = []

    async def send(event):
        events.append(event)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/pipelines",
        "raw_path": b"/pipelines",
        "query_string": b"",
        "root_path": "",
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "headers": [(b"content-type", b"application/json")]
        + ([(b"authorization", authorization)] if authorization else [])
        + (headers or []),
    }
    asyncio.run(app(scope, receive, send))
    return next(event["status"] for event in events if event["type"] == "http.response.start")


def test_unauthorized_requests_do_not_read_an_attacker_body(tmp_path, monkeypatch):
    from pipefoundry.api import create_app

    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "t" * 32)
    reads = 0

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"{}", "more_body": False}

    assert exchange(create_app(tmp_path), receive) == 401
    assert reads == 0


def test_authenticated_slow_body_has_a_total_read_deadline(tmp_path, monkeypatch):
    import pipefoundry.api as api

    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "t" * 32)
    monkeypatch.setattr(api, "BODY_READ_TIMEOUT", 0.05, raising=False)

    async def receive():
        await asyncio.sleep(0.15)
        return {"type": "http.request", "body": b"{}", "more_body": False}

    assert exchange(api.create_app(tmp_path), receive, b"Bearer " + b"t" * 32) == 408


def test_declared_oversize_body_is_rejected_before_reading_it(tmp_path, monkeypatch):
    from pipefoundry.api import create_app

    monkeypatch.setenv("PIPEFOUNDRY_API_TOKEN", "t" * 32)
    reads = 0

    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"{}", "more_body": False}

    assert (
        exchange(
            create_app(tmp_path),
            receive,
            b"Bearer " + b"t" * 32,
            [(b"content-length", b"999999999999999999")],
        )
        == 413
    )
    assert reads == 0
