"""Authenticated control plane. Run behind TLS and a rate-limiting reverse proxy."""

import asyncio
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import Field

from pipefoundry.console import CSP, render_console
from pipefoundry.demo import DEMO_KEY, DEMO_NAME, demo_ready, demo_receipt, seed_demo
from pipefoundry.engine import Platform
from pipefoundry.models import Pipeline, StrictModel
from pipefoundry.release_models import ApplyRequest, RecoveryRequest, ReleaseRequest
from pipefoundry.releases import ReleaseSentinel
from pipefoundry.workbench import PAGES
from pipefoundry.workbench import router as workbench_router

MAX_BODY_BYTES = 32768
BODY_READ_TIMEOUT = 5.0


def secure_response(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


class Deployment(StrictModel):
    config: Pipeline
    executor: Literal["local", "kubernetes"] = "local"


class PreviewChange(StrictModel):
    path: Literal[
        "config",
        "executor",
        "config.name",
        "config.schedule",
        "config.transform",
        "config.input.connector",
        "config.input.path",
        "config.output.connector",
        "config.output.path",
        "config.resources.cpu_millis",
        "config.resources.memory_mib",
    ]
    kind: Literal["added", "changed"]


class PreviewCurrent(StrictModel):
    revision: int = Field(ge=1)
    status: Literal[
        "rendering",
        "rendered",
        "running",
        "deploying",
        "succeeded",
        "deployed",
        "failed",
        "torn_down",
    ]
    executor: Literal["local", "kubernetes", "render"]
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeploymentPreview(StrictModel):
    name: str
    action: Literal["create", "update", "no-op"]
    current: PreviewCurrent | None
    desired_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: list[PreviewChange] = Field(max_length=12)
    changes_truncated: bool
    operation_in_progress: bool
    comparison: str


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


def create_app(
    root: str | Path | None = None, *, demo_name=DEMO_NAME, demo_key=DEMO_KEY
) -> FastAPI:
    platform = Platform(root or os.environ.get("PIPEFOUNDRY_STATE_DIR", ".pipefoundry"))
    public_demo = os.environ.get(
        "PIPEFOUNDRY_PUBLIC_DEMO", os.environ.get("PUBLIC_DEMO", "false")
    ).lower() in {"1", "true"}
    auto_seed = os.environ.get(
        "PIPEFOUNDRY_SEED_DEMO", os.environ.get("SEED_DEMO", "true")
    ).lower() in {"1", "true"}
    cache = {"expires": 0.0, "receipt": None}
    cache_lock = threading.Lock()

    async def bootstrap():
        try:
            await asyncio.to_thread(seed_demo, platform, name=demo_name, key=demo_key)
            cache["expires"] = 0.0
        except Exception as exc:
            logging.getLogger(__name__).error("demo initialization failed (%s)", type(exc).__name__)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(bootstrap()) if public_demo and auto_seed else None
        try:
            yield
        finally:
            if task and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=25)
                except TimeoutError:
                    task.cancel()

    app = FastAPI(
        title="PipeFoundry", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan
    )
    authenticated = [Depends(authorize)]

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        if request.url.path in {
            "/deployments/preview",
            "/workbench/api/validate",
            "/workbench/api/review",
            "/workbench/api/agent",
            "/workbench/api/demo-agent",
        } or request.url.path.startswith("/releases/"):
            # Pydantic's default errors include input and unknown field names.
            # A preview must never reflect accidentally pasted credentials.
            return JSONResponse({"detail": "invalid deployment configuration"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware("http")
    async def limit_body(request: Request, call_next):
        # Reject unknown credentials without consuming an attacker-controlled
        # stream. Route dependencies still recheck before executing an action.
        path = request.url.path
        workbench_pages = {"/", "/workbench"} | {f"/workbench/{page}" for page in PAGES}
        public_read = request.method in {"GET", "HEAD"} and (
            path in workbench_pages
            or path
            in {
                "/workbench/assets/app.css",
                "/workbench/assets/app.js",
                "/workbench/assets/ui.js",
                "/workbench/api/github",
                "/workbench/api/integrations",
            }
        )
        public_validation = request.method == "POST" and path in {
            "/workbench/api/validate",
            "/workbench/api/review",
            "/workbench/api/demo-agent",
        }
        if (
            not public_read
            and not public_validation
            and path not in {"/health/live", "/health/ready"}
        ):
            try:
                authorize(request.headers.get("authorization"))
            except HTTPException as exc:
                return secure_response(
                    JSONResponse(
                        {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
                    )
                )
        declared = request.headers.get("content-length")
        if declared is not None:
            if not declared.isascii() or not declared.isdecimal():
                return secure_response(
                    JSONResponse({"detail": "invalid content length"}, status_code=400)
                )
            if len(declared) > 8 or int(declared) > MAX_BODY_BYTES:
                return secure_response(
                    JSONResponse({"detail": "request body exceeds 32 KiB"}, status_code=413)
                )
        body = bytearray()
        try:
            async with asyncio.timeout(BODY_READ_TIMEOUT):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        return secure_response(
                            JSONResponse({"detail": "request body exceeds 32 KiB"}, status_code=413)
                        )
                    body.extend(chunk)
        except TimeoutError:
            return secure_response(
                JSONResponse({"detail": "request body read deadline exceeded"}, status_code=408)
            )
        request._body = bytes(body)
        response = await call_next(request)
        return secure_response(response)

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
        if platform.durable and not os.environ.get("PIPEFOUNDRY_POSTGRES_DSN"):
            raise HTTPException(503, "hosted PostgreSQL output is not configured")
        if public_demo and not demo_ready(platform, key=demo_key):
            raise HTTPException(503, "public demo initialization is pending")
        with platform.connect() as connection:
            connection.execute("SELECT 1")
        return {"status": "ready"}

    def public_receipt():
        if not public_demo:
            raise HTTPException(404, "public demo is disabled")
        with cache_lock:
            if time.monotonic() >= cache["expires"]:
                try:
                    cache["receipt"] = demo_receipt(platform, name=demo_name, key=demo_key)
                    cache["expires"] = time.monotonic() + 5
                except (ValueError, LookupError, StopIteration, psycopg.Error):
                    cache["receipt"] = None
                    cache["expires"] = time.monotonic() + 2
            if cache["receipt"] is None:
                raise HTTPException(503, "public demo initialization is pending")
            return cache["receipt"]

    @app.get("/demo")
    def read_demo():
        return public_receipt()

    @app.get("/demo/console", response_class=HTMLResponse)
    def read_console():
        if not public_demo:
            raise HTTPException(404, "public demo is disabled")
        try:
            return HTMLResponse(
                render_console(public_receipt()), headers={"Content-Security-Policy": CSP}
            )
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            return HTMLResponse(
                render_console(None),
                status_code=503,
                headers={"Content-Security-Policy": CSP, "Retry-After": "5"},
            )

    @app.post("/demo/seed", dependencies=authenticated)
    def initialize_demo():
        if not public_demo:
            raise HTTPException(404, "public demo is disabled")
        completed = seed_demo(platform, name=demo_name, key=demo_key)
        cache["expires"] = 0.0
        if not completed:
            return JSONResponse({"status": "initializing"}, status_code=202)
        return public_receipt()

    @app.get("/pipelines", dependencies=authenticated)
    def pipelines():
        return platform.list()

    @app.post("/pipelines", status_code=201, dependencies=authenticated)
    def deploy(body: Deployment):
        return platform.deploy(body.config, body.executor)

    @app.post("/deployments/preview", dependencies=authenticated, response_model=DeploymentPreview)
    def preview_deployment(body: Deployment):
        return platform.preview(body.config, body.executor)

    @app.post("/render", status_code=201, dependencies=authenticated)
    def render_pipeline(body: Pipeline):
        return platform.render(body)

    @app.post("/releases/plan", dependencies=authenticated)
    def release_plan(body: ReleaseRequest):
        return ReleaseSentinel(platform).plan(
            body.config, body.executor, policy=body.policy, ttl_seconds=body.ttl_seconds
        )

    @app.post("/releases/apply", dependencies=authenticated)
    def release_apply(body: ApplyRequest):
        return ReleaseSentinel(platform).apply(body.plan_id, body.digest, body.idempotency_key)

    @app.get("/releases/receipts/{key}", dependencies=authenticated)
    def release_receipt(key: str):
        return ReleaseSentinel(platform).receipt(key)

    @app.post("/releases/recover", dependencies=authenticated)
    def release_recover(body: RecoveryRequest):
        return ReleaseSentinel(platform).recover(
            body.idempotency_key, confirm_worker_stopped=body.confirm_worker_stopped
        )

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

    app.include_router(workbench_router(authorize))
    return app


app = create_app()
