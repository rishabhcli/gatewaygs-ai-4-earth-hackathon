"""Semantic liveness/readiness and dependency failure tests."""

from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx
import psycopg
import pytest
from pydantic import SecretStr, ValidationError

from services.api import app as api_module
from services.runtime import health as health_module
from services.runtime.health import (
    CheckStatus,
    DependencyCheck,
    HealthResponse,
    HealthStatus,
)
from workers.acquisition import health_app as worker_health_module

if TYPE_CHECKING:
    from services.runtime.config import RuntimeSettings


@pytest.mark.parametrize(
    ("health_status", "expected_http_status"),
    [
        (HealthStatus.ALIVE, 200),
        (HealthStatus.READY, 200),
        (HealthStatus.NOT_READY, 503),
    ],
)
def test_health_contract_maps_state_to_http_semantics(
    health_status: HealthStatus, expected_http_status: int
) -> None:
    response = HealthResponse(service="api", status=health_status)

    assert response.http_status == expected_http_status


def test_health_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HealthResponse(service="api", status=HealthStatus.READY, fabricated=True)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        DependencyCheck(
            name="postgis",
            status=CheckStatus.PASS,
            code="POSTGIS_QUERY_OK",
            fabricated=True,  # type: ignore[call-arg]
        )


def test_postgis_provider_error_becomes_stable_failure_without_secret_leak(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive_value = "postgres-credential-that-must-never-escape"
    dsn = SecretStr(f"postgresql://service:{sensitive_value}@127.0.0.1:4175/catalog")

    def fail_connect(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise psycopg.OperationalError(f"provider echoed {sensitive_value}")

    monkeypatch.setattr("services.runtime.health.psycopg.connect", fail_connect)

    result = asyncio.run(health_module.probe_postgis(dsn, timeout_seconds=0.1))
    rendered = json.dumps(result.model_dump(mode="json")) + caplog.text

    assert result == DependencyCheck(
        name="postgis",
        status=CheckStatus.FAIL,
        code="POSTGIS_UNAVAILABLE",
    )
    assert sensitive_value not in rendered
    assert "postgresql://" not in rendered


def test_postgis_empty_version_becomes_stable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, query: str) -> None:
            assert query == "SELECT postgis_version()"

        def fetchone(self) -> None:
            return None

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(
        "services.runtime.health.psycopg.connect",
        lambda *_args, **_kwargs: Connection(),
    )

    result = asyncio.run(
        health_module.probe_postgis(SecretStr("redacted-dsn"), timeout_seconds=0.1)
    )

    assert result.status is CheckStatus.FAIL
    assert result.code == "POSTGIS_UNAVAILABLE"


def test_postgis_version_query_success_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def execute(self, query: str) -> None:
            assert query == "SELECT postgis_version()"

        def fetchone(self) -> tuple[str]:
            return ("3.6.2",)

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def cursor(self) -> Cursor:
            return Cursor()

    monkeypatch.setattr(
        "services.runtime.health.psycopg.connect",
        lambda *_args, **_kwargs: Connection(),
    )

    result = asyncio.run(
        health_module.probe_postgis(SecretStr("redacted-dsn"), timeout_seconds=0.1)
    )

    assert result == DependencyCheck(
        name="postgis",
        status=CheckStatus.PASS,
        code="POSTGIS_QUERY_OK",
    )


def test_object_store_network_error_becomes_stable_failure_without_url_leak(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive_value = "object-store-credential-that-must-not-escape"
    ready_url = "http://127.0.0.1:4176/minio/health/ready?credential=" + sensitive_value

    class FailingClient:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["follow_redirects"] is False

        async def __aenter__(self) -> FailingClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def get(self, url: str) -> httpx.Response:
            request = httpx.Request("GET", url)
            raise httpx.ConnectError(
                f"provider echoed {sensitive_value}", request=request
            )

    monkeypatch.setattr("services.runtime.health.httpx.AsyncClient", FailingClient)

    result = asyncio.run(
        health_module.probe_object_store(ready_url, timeout_seconds=0.1)
    )
    rendered = json.dumps(result.model_dump(mode="json")) + caplog.text

    assert result == DependencyCheck(
        name="object-store",
        status=CheckStatus.FAIL,
        code="OBJECT_STORE_UNAVAILABLE",
    )
    assert sensitive_value not in rendered
    assert ready_url not in rendered


def test_object_store_non_200_response_is_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NonReadyClient:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        async def __aenter__(self) -> NonReadyClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def get(self, url: str) -> httpx.Response:
            return httpx.Response(503, request=httpx.Request("GET", url))

    monkeypatch.setattr("services.runtime.health.httpx.AsyncClient", NonReadyClient)

    result = asyncio.run(
        health_module.probe_object_store(
            "http://127.0.0.1:4176/minio/health/ready", timeout_seconds=0.1
        )
    )

    assert result.status is CheckStatus.FAIL
    assert result.code == "OBJECT_STORE_UNAVAILABLE"


def test_object_store_200_response_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReadyClient:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        async def __aenter__(self) -> ReadyClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def get(self, url: str) -> httpx.Response:
            return httpx.Response(HTTPStatus.OK, request=httpx.Request("GET", url))

    monkeypatch.setattr("services.runtime.health.httpx.AsyncClient", ReadyClient)

    result = asyncio.run(
        health_module.probe_object_store(
            "http://127.0.0.1:4176/minio/health/ready", timeout_seconds=0.1
        )
    )

    assert result == DependencyCheck(
        name="object-store",
        status=CheckStatus.PASS,
        code="OBJECT_STORE_READY",
    )


def _check(name: str, *, passed: bool) -> DependencyCheck:
    return DependencyCheck(
        name=name,
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        code=(
            "POSTGIS_QUERY_OK"
            if name == "postgis" and passed
            else "POSTGIS_UNAVAILABLE"
            if name == "postgis"
            else "OBJECT_STORE_READY"
            if passed
            else "OBJECT_STORE_UNAVAILABLE"
        ),
    )


async def _get_api_health(app: object) -> tuple[httpx.Response, httpx.Response]:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://unit.test"
    ) as client:
        return await client.get("/livez"), await client.get("/readyz")


@pytest.mark.parametrize(
    "case",
    [
        (True, True, HTTPStatus.OK, "ready"),
        (False, True, HTTPStatus.SERVICE_UNAVAILABLE, "not-ready"),
        (True, False, HTTPStatus.SERVICE_UNAVAILABLE, "not-ready"),
        (False, False, HTTPStatus.SERVICE_UNAVAILABLE, "not-ready"),
    ],
)
def test_api_readiness_requires_every_dependency_but_liveness_does_not(
    monkeypatch: pytest.MonkeyPatch,
    api_settings: RuntimeSettings,
    case: tuple[bool, bool, HTTPStatus, str],
) -> None:
    postgis_passes, object_store_passes, expected_status, expected_body = case

    async def postgis_probe(*args: object, **kwargs: object) -> DependencyCheck:
        del args, kwargs
        return _check("postgis", passed=postgis_passes)

    async def object_store_probe(*args: object, **kwargs: object) -> DependencyCheck:
        del args, kwargs
        return _check("object-store", passed=object_store_passes)

    monkeypatch.setattr(api_module, "load_settings", lambda _role: api_settings)
    monkeypatch.setattr(api_module, "probe_postgis", postgis_probe)
    monkeypatch.setattr(api_module, "probe_object_store", object_store_probe)

    live, ready = asyncio.run(_get_api_health(api_module.create_app()))

    assert live.status_code == HTTPStatus.OK
    assert live.json()["status"] == "alive"
    assert live.json()["checks"] == []
    assert ready.status_code == expected_status
    assert ready.json()["status"] == expected_body
    assert {check["name"] for check in ready.json()["checks"]} == {
        "postgis",
        "object-store",
    }


@pytest.mark.parametrize(
    "case",
    [
        (True, HTTPStatus.OK, "ready"),
        (False, HTTPStatus.SERVICE_UNAVAILABLE, "not-ready"),
    ],
)
def test_worker_health_uses_same_semantic_readiness_contract(
    monkeypatch: pytest.MonkeyPatch,
    worker_settings: RuntimeSettings,
    case: tuple[bool, HTTPStatus, str],
) -> None:
    dependency_passes, expected_status, expected_body = case

    async def postgis_probe(*args: object, **kwargs: object) -> DependencyCheck:
        del args, kwargs
        return _check("postgis", passed=dependency_passes)

    async def object_store_probe(*args: object, **kwargs: object) -> DependencyCheck:
        del args, kwargs
        return _check("object-store", passed=dependency_passes)

    monkeypatch.setattr(
        worker_health_module, "load_settings", lambda _role: worker_settings
    )
    monkeypatch.setattr(worker_health_module, "probe_postgis", postgis_probe)
    monkeypatch.setattr(worker_health_module, "probe_object_store", object_store_probe)

    live, ready = asyncio.run(_get_api_health(worker_health_module.create_app()))

    assert live.status_code == HTTPStatus.OK
    assert live.json()["status"] == "alive"
    assert ready.status_code == expected_status
    assert ready.json()["status"] == expected_body
