"""Correlation-ID and structurally redacted JSON logging tests."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from http import HTTPStatus
from io import StringIO
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from hypothesis import (
    HealthCheck,
    given,
)
from hypothesis import (
    settings as hypothesis_settings,
)
from hypothesis import (
    strategies as st,
)

from services.runtime import observability

if TYPE_CHECKING:
    import pytest


class _StructuredLogRecord(logging.LogRecord):
    event_name: str
    service: str
    correlation_id: str
    http_method: str
    safe_path: str
    status_code: int
    duration_ms: float
    authorization: str
    password: str
    request_body: dict[str, str]


def _is_invalid_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return True
    except AttributeError:
        return True
    return False


@hypothesis_settings(max_examples=128, derandomize=True)
@given(value=st.uuids())
def test_property_canonical_correlation_id_is_preserved(value: UUID) -> None:
    """Property cases: 128 canonical UUID correlation IDs round-trip exactly."""

    raw = str(value)
    assert observability.valid_or_new_correlation_id(raw) == raw


@hypothesis_settings(
    max_examples=256,
    derandomize=True,
    suppress_health_check=(HealthCheck.filter_too_much,),
)
@given(
    raw=st.text(
        min_size=0,
        max_size=512,
    ).filter(_is_invalid_uuid)
)
def test_property_invalid_correlation_id_is_never_reflected(raw: str) -> None:
    """Property cases: 256 invalid IDs are replaced with canonical UUIDs."""

    replacement = observability.valid_or_new_correlation_id(raw)

    assert str(UUID(replacement)) == replacement
    assert replacement != raw


def test_missing_correlation_ids_receive_distinct_canonical_values() -> None:
    first = observability.valid_or_new_correlation_id(None)
    second = observability.valid_or_new_correlation_id(None)

    assert str(UUID(first)) == first
    assert str(UUID(second)) == second
    assert first != second


def test_json_formatter_emits_only_fixed_fields_and_excludes_record_payload() -> None:
    sensitive_value = "authorization-bearer-sensitive-value"
    record = _StructuredLogRecord(
        name="gatewaygs.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=f"untrusted message with {sensitive_value}",
        args=(),
        exc_info=None,
    )
    record.event_name = "http.request.completed"
    record.service = "api"
    record.correlation_id = str(uuid4())
    record.http_method = "GET"
    record.safe_path = "/readyz"
    record.status_code = 200
    record.duration_ms = 1.25
    record.authorization = sensitive_value
    record.password = sensitive_value
    record.request_body = {"token": sensitive_value}

    rendered = observability.JsonFormatter().format(record)
    event = json.loads(rendered)

    assert set(event) == {
        "timestamp",
        "level",
        "event",
        "service",
        "correlation_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
    }
    assert event | {"timestamp": None} == {
        "timestamp": None,
        "level": "INFO",
        "event": "http.request.completed",
        "service": "api",
        "correlation_id": record.correlation_id,
        "method": "GET",
        "path": "/readyz",
        "status_code": 200,
        "duration_ms": 1.25,
    }
    utc_offset = datetime.fromisoformat(event["timestamp"]).utcoffset()
    assert utc_offset is not None
    assert utc_offset.total_seconds() == 0
    assert sensitive_value not in rendered
    assert "authorization" not in rendered
    assert "request_body" not in rendered


def test_request_logging_does_not_log_query_secrets_and_returns_correlation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(observability.JsonFormatter())
    logger = logging.getLogger(f"test.gatewaygs.{uuid4()}")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    monkeypatch.setattr(observability, "configure_logging", lambda _service: logger)

    app = FastAPI()
    observability.install_request_logging(app, "api")

    @app.get("/v1/status")
    async def status() -> dict[str, bool]:
        return {"ok": True}

    sensitive_value = "query-credential-must-not-be-logged"
    invalid_header = "not-a-uuid-and-not-safe-to-reflect"

    async def make_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://unit.test"
        ) as client:
            return await client.get(
                f"/v1/status?credential={sensitive_value}",
                headers={"x-correlation-id": invalid_header},
            )

    response = asyncio.run(make_request())

    returned_id = response.headers["x-correlation-id"]
    log_line = stream.getvalue().strip()
    event = json.loads(log_line)

    assert response.status_code == HTTPStatus.OK
    assert str(UUID(returned_id)) == returned_id
    assert returned_id != invalid_header
    assert event["correlation_id"] == returned_id
    assert event["path"] == "/v1/status"
    assert sensitive_value not in log_line
    assert invalid_header not in log_line
    assert set(event) == {
        "timestamp",
        "level",
        "event",
        "service",
        "correlation_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
    }
