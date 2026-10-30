"""Closed, bounded inputs for release review and execution."""

from typing import Literal

from pydantic import Field

from pipefoundry.models import Pipeline, StrictModel


class RolloutPolicy(StrictModel):
    # Deliberately explicit: changing a create plan into an update needs a new review.
    allowed_operation: Literal["create", "update", "no-op"] | None = None
    max_cpu_millis: int = Field(default=4000, ge=50, le=4000, strict=True)
    max_memory_mib: int = Field(default=8192, ge=64, le=8192, strict=True)
    max_input_rows: int = Field(default=10000, ge=1, le=10000, strict=True)


class ReleaseRequest(StrictModel):
    config: Pipeline
    executor: Literal["local", "kubernetes"] = "local"
    policy: RolloutPolicy = Field(default_factory=RolloutPolicy)
    ttl_seconds: int = Field(default=300, ge=1, le=3600, strict=True)


class PlanReference(StrictModel):
    plan_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ApplyRequest(PlanReference):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


class RecoveryRequest(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    confirm_worker_stopped: bool = Field(strict=True)
