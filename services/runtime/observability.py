"""Structured, redacted request logging with correlation IDs."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, Response
    from starlette.middleware.base import RequestResponseEndpoint
    from starlette.types import ASGIApp


_SAFE_REQUEST_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{0,255}$")


class JsonFormatter(logging.Formatter):
    """Emit a fixed allowlist of fields; arbitrary record values are excluded."""

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event_name", "runtime.log"),
            "service": getattr(record, "service", "unknown"),
            "correlation_id": getattr(record, "correlation_id", None),
            "method": getattr(record, "http_method", None),
            "path": getattr(record, "safe_path", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }
        return json.dumps(event, separators=(",", ":"), sort_keys=True)


def configure_logging(service: str) -> logging.Logger:
    logger = logging.getLogger(f"gatewaygs.{service}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


def valid_or_new_correlation_id(raw: str | None) -> str:
    if raw is not None:
        try:
            return str(UUID(raw))
        except ValueError:
            pass
    return str(uuid4())


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that logs only an explicit safe field allowlist."""

    def __init__(self, app: ASGIApp, service: str) -> None:
        super().__init__(app)
        self.service = service
        self.logger = configure_logging(service)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        correlation_id = valid_or_new_correlation_id(
            request.headers.get("x-correlation-id")
        )
        started = monotonic()
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        path = request.url.path
        safe_path = path if _SAFE_REQUEST_PATH.fullmatch(path) else "[redacted]"
        self.logger.info(
            "request handled",
            extra={
                "event_name": "http.request.completed",
                "service": self.service,
                "correlation_id": correlation_id,
                "http_method": request.method,
                "safe_path": safe_path,
                "status_code": response.status_code,
                "duration_ms": round((monotonic() - started) * 1000, 3),
            },
        )
        return response


def install_request_logging(app: FastAPI, service: str) -> None:
    app.add_middleware(RequestLoggingMiddleware, service=service)
