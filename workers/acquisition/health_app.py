"""Health/status surface for the acquisition worker boundary."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Response

from services.runtime.config import ServiceRole, load_settings
from services.runtime.health import (
    CheckStatus,
    HealthResponse,
    HealthStatus,
    probe_object_store,
    probe_postgis,
)
from services.runtime.observability import install_request_logging


def create_app() -> FastAPI:
    settings = load_settings(ServiceRole.WORKER_HEALTH)
    app = FastAPI(
        title="Acquisition worker health",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_request_logging(app, ServiceRole.WORKER_HEALTH.value)

    @app.get("/livez", response_model=HealthResponse)
    async def livez() -> HealthResponse:
        return HealthResponse(service="worker-health", status=HealthStatus.ALIVE)

    @app.get("/readyz", response_model=HealthResponse)
    async def readyz(response: Response) -> HealthResponse:
        postgis, object_store = await asyncio.gather(
            probe_postgis(
                settings.database.dsn(settings.repository_root),
                settings.dependency_timeout_seconds,
            ),
            probe_object_store(
                str(settings.object_store_ready_url),
                settings.dependency_timeout_seconds,
            ),
        )
        checks = [postgis, object_store]
        result = HealthResponse(
            service="worker-health",
            status=(
                HealthStatus.READY
                if all(check.status is CheckStatus.PASS for check in checks)
                else HealthStatus.NOT_READY
            ),
            checks=checks,
        )
        response.status_code = result.http_status
        return result

    return app
