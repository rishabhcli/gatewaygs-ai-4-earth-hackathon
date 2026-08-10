"""Versioned health contracts and dependency probes."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Annotated, Literal

import httpx
import psycopg
from fastapi import status
from pydantic import BaseModel, ConfigDict, Field, SecretStr


class HealthStatus(StrEnum):
    ALIVE = "alive"
    READY = "ready"
    NOT_READY = "not-ready"


class CheckStatus(StrEnum):
    PASS = "pass"  # noqa: S105 - this is a health result, never a password
    FAIL = "fail"


class DependencyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    status: CheckStatus
    code: str = Field(min_length=1, max_length=96, pattern=r"^[A-Z0-9_]+$")


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1"] = "1"
    service: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9-]+$")
    status: HealthStatus
    checks: Annotated[list[DependencyCheck], Field(max_length=16)] = Field(
        default_factory=list
    )

    @property
    def http_status(self) -> int:
        if self.status in {HealthStatus.ALIVE, HealthStatus.READY}:
            return status.HTTP_200_OK
        return status.HTTP_503_SERVICE_UNAVAILABLE


async def probe_postgis(dsn: SecretStr, timeout_seconds: float) -> DependencyCheck:
    """Verify query execution and the PostGIS extension, without leaking DSN."""

    def query() -> str:
        with (
            psycopg.connect(
                dsn.get_secret_value(), connect_timeout=max(1, int(timeout_seconds))
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT postgis_version()")
            row = cursor.fetchone()
            if row is None or not isinstance(row[0], str) or not row[0]:
                raise RuntimeError("PostGIS returned no version")
            return row[0]

    try:
        await asyncio.wait_for(asyncio.to_thread(query), timeout=timeout_seconds + 0.5)
    except OSError, RuntimeError, psycopg.Error, TimeoutError:
        return DependencyCheck(
            name="postgis", status=CheckStatus.FAIL, code="POSTGIS_UNAVAILABLE"
        )
    return DependencyCheck(
        name="postgis", status=CheckStatus.PASS, code="POSTGIS_QUERY_OK"
    )


async def probe_object_store(ready_url: str, timeout_seconds: float) -> DependencyCheck:
    """Verify the provider's readiness endpoint, not merely an open socket."""

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds), follow_redirects=False
        ) as client:
            response = await client.get(ready_url)
    except httpx.HTTPError:
        return DependencyCheck(
            name="object-store",
            status=CheckStatus.FAIL,
            code="OBJECT_STORE_UNAVAILABLE",
        )
    if response.status_code != status.HTTP_200_OK:
        return DependencyCheck(
            name="object-store",
            status=CheckStatus.FAIL,
            code="OBJECT_STORE_UNAVAILABLE",
        )
    return DependencyCheck(
        name="object-store",
        status=CheckStatus.PASS,
        code="OBJECT_STORE_READY",
    )
