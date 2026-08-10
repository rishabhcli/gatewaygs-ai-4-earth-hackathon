"""FastAPI operational control plane.

Tier 0 deliberately exposes no job-creation endpoint: accepting analysis work
before the retrieval and persistence path exists would be fabricated success.
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel, ConfigDict

from services.runtime.config import ServiceRole, load_settings
from services.runtime.health import (
    CheckStatus,
    HealthResponse,
    HealthStatus,
    probe_object_store,
    probe_postgis,
)
from services.runtime.observability import install_request_logging


class ProductState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["1"] = "1"
    production_state: Literal["not-yet-in-production"] = "not-yet-in-production"
    analysis_jobs_supported: Literal[False] = False
    reason_code: Literal["PIPELINE_NOT_IMPLEMENTED"] = "PIPELINE_NOT_IMPLEMENTED"


def create_app() -> FastAPI:
    settings = load_settings(ServiceRole.API)
    app = FastAPI(
        title="Methane evidence job control plane",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    install_request_logging(app, ServiceRole.API.value)

    @app.get("/livez", response_model=HealthResponse)
    async def livez() -> HealthResponse:
        return HealthResponse(service="api", status=HealthStatus.ALIVE)

    @app.get("/readyz", response_model=HealthResponse)
    async def readyz(response: Response) -> HealthResponse:
        dsn = settings.database.dsn(settings.repository_root)
        postgis, object_store = await asyncio.gather(
            probe_postgis(dsn, settings.dependency_timeout_seconds),
            probe_object_store(
                str(settings.object_store_ready_url),
                settings.dependency_timeout_seconds,
            ),
        )
        checks = [postgis, object_store]
        readiness = HealthResponse(
            service="api",
            status=(
                HealthStatus.READY
                if all(check.status is CheckStatus.PASS for check in checks)
                else HealthStatus.NOT_READY
            ),
            checks=checks,
        )
        response.status_code = readiness.http_status
        return readiness

    @app.get("/v1/status", response_model=ProductState)
    async def product_status() -> ProductState:
        return ProductState()

    return app
