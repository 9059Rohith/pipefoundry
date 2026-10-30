"""Authenticated control plane. Run behind TLS and a rate-limiting reverse proxy."""

import os
import secrets
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline, StrictModel


class Deployment(StrictModel):
    config: Pipeline
    executor: Literal["local", "kubernetes"] = "local"


class Backfill(StrictModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class Rollback(StrictModel):
    revision: int = Field(ge=1, le=1_000_000, strict=True)


def authorize(authorization: Annotated[str | None, Header()] = None):
    expected = os.environ.get("PIPEFOUNDRY_API_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "API token is not configured securely")
    supplied = (authorization or "").encode("utf-8")
    if not secrets.compare_digest(supplied, ("Bearer " + expected).encode("utf-8")):
        raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})


def create_app(root: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="PipeFoundry", version="0.1.0", docs_url=None, redoc_url=None)
    platform = Platform(root or os.environ.get("PIPEFOUNDRY_STATE_DIR", ".pipefoundry"))
    authenticated = [Depends(authorize)]

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 32768:
                return JSONResponse({"detail": "request body exceeds 32 KiB"}, status_code=413)
            body.extend(chunk)
        request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(RuntimeError)
    async def failed(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        if len(os.environ.get("PIPEFOUNDRY_API_TOKEN", "")) < 32:
            raise HTTPException(503, "API token is not configured securely")
        with platform.connect() as connection:
            connection.execute("SELECT 1")
        return {"status": "ready"}

    @app.get("/pipelines", dependencies=authenticated)
    def pipelines():
        return platform.list()

    @app.post("/pipelines", status_code=201, dependencies=authenticated)
    def deploy(body: Deployment):
        return platform.deploy(body.config, body.executor)

    @app.post("/render", status_code=201, dependencies=authenticated)
    def render_pipeline(body: Pipeline):
        return platform.render(body)

    @app.get("/pipelines/{name}", dependencies=authenticated)
    def status(name: str):
        return platform.status(name, refresh=True)

    @app.get("/pipelines/{name}/logs", dependencies=authenticated)
    def logs(name: str):
        return {"logs": platform.logs(name)}

    @app.get("/pipelines/{name}/audit", dependencies=authenticated)
    def audit(name: str):
        return {"events": platform.audit(name)}

    @app.post("/pipelines/{name}/backfill", dependencies=authenticated)
    def backfill(name: str, body: Backfill):
        return platform.backfill(name, body.start, body.end)

    @app.post("/pipelines/{name}/rollback", dependencies=authenticated)
    def rollback(name: str, body: Rollback):
        return platform.rollback(name, body.revision)

    @app.delete("/pipelines/{name}", dependencies=authenticated)
    def teardown(name: str):
        return platform.teardown(name)

    return app


app = create_app()
