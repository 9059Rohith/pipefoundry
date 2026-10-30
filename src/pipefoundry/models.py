"""Config is data, never code: all execution choices are closed enumerations."""

import re
from pathlib import PurePosixPath
from typing import Literal

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

NAME = re.compile(r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$|^[a-z]$")


def valid_name(value: str) -> str:
    if not NAME.fullmatch(value):
        raise ValueError("name must be 1-40 lowercase alphanumeric/hyphen characters")
    return value


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 160
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {".", ".."} for part in value.split("/"))
        or not re.fullmatch(r"[a-zA-Z0-9_./-]+", value)
    ):
        raise ValueError("path must be a safe relative path under the data root")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Input(StrictModel):
    connector: Literal["fixture", "orders_api", "spark_json"] = "fixture"
    path: str = "orders.json"

    _safe_path = field_validator("path")(relative_path)


class Output(StrictModel):
    connector: Literal["sqlite", "postgres", "parquet"] = "sqlite"
    path: str = "orders.db"

    _safe_path = field_validator("path")(relative_path)


class Resources(StrictModel):
    cpu_millis: int = Field(default=250, ge=50, le=4000, strict=True)
    memory_mib: int = Field(default=256, ge=64, le=8192, strict=True)


class Pipeline(StrictModel):
    name: str
    schedule: str = Field(max_length=80)
    input: Input = Field(default_factory=Input)
    transform: Literal["normalize_orders"] = "normalize_orders"
    output: Output = Field(default_factory=Output)
    resources: Resources = Field(default_factory=Resources)

    _name = field_validator("name")(valid_name)

    @field_validator("schedule")
    @classmethod
    def schedule_valid(cls, value: str) -> str:
        if len(value.split()) != 5 or not croniter.is_valid(value):
            raise ValueError("schedule must be a five-field cron expression in UTC")
        return value

    @model_validator(mode="after")
    def compatible_connectors(self):
        if (self.input.connector == "spark_json") != (self.output.connector == "parquet"):
            raise ValueError("spark_json requires parquet output and vice versa")
        if self.input.connector == "spark_json" and self.resources.memory_mib < 1024:
            raise ValueError("Spark requires at least 1024 MiB")
        return self
