"""Immutable asset integrity and truthful product-state tests."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from fastapi import HTTPException
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
from pydantic import ValidationError

from services.api import app as api_module
from services.api import assets as assets_module
from services.api.app import ProductState

if TYPE_CHECKING:
    from pathlib import Path

    from services.runtime.config import RuntimeSettings


_VALID_DIGEST = re.compile(r"^[a-f0-9]{64}$")


async def _request(
    app: object,
    method: str,
    path: str,
    *,
    json_body: dict[str, object] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(
        transport=transport, base_url="http://unit.test"
    ) as client:
        return await client.request(method, path, json=json_body)


def _error_detail(error: HTTPException) -> dict[str, object]:
    return cast("dict[str, object]", error.detail)


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "abc",
        "A" * 64,
        "g" * 64,
        "0" * 63,
        "0" * 65,
        "../" + ("0" * 64),
        ("0" * 32) + "/../" + ("0" * 32),
        "%2e%2e%2f" + ("0" * 64),
        "0" * 63 + "\n",
    ],
)
def test_asset_path_refuses_malformed_or_traversal_digest(
    tmp_path: Path, digest: str
) -> None:
    with pytest.raises(HTTPException) as raised:
        assets_module._asset_path(tmp_path, digest)

    assert raised.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _error_detail(raised.value) == {
        "code": "INVALID_CONTENT_DIGEST",
        "retryable": False,
    }


@hypothesis_settings(
    max_examples=256,
    derandomize=True,
    suppress_health_check=(
        HealthCheck.filter_too_much,
        HealthCheck.function_scoped_fixture,
    ),
)
@given(
    digest=st.text(
        min_size=0,
        max_size=96,
    ).filter(lambda value: _VALID_DIGEST.fullmatch(value) is None)
)
def test_property_invalid_content_digest_never_reaches_filesystem(
    tmp_path: Path, digest: str
) -> None:
    """Property cases: 256 malformed digest strings fail before file access."""

    with pytest.raises(HTTPException) as raised:
        assets_module._asset_path(tmp_path, digest)
    assert raised.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _error_detail(raised.value)["code"] == "INVALID_CONTENT_DIGEST"


def test_asset_path_refuses_prefix_symlink_traversal(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets"
    asset_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    digest = "a" * 64
    (asset_root / "aa").symlink_to(outside, target_is_directory=True)

    with pytest.raises(HTTPException) as raised:
        assets_module._asset_path(asset_root, digest)

    assert raised.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert _error_detail(raised.value) == {
        "code": "ASSET_PATH_ESCAPE",
        "retryable": False,
    }


def test_asset_server_serves_only_bytes_matching_requested_digest(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings
) -> None:
    content = b"verified immutable scene overlay"
    digest = hashlib.sha256(content).hexdigest()
    path = asset_settings.asset_root / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)

    response = asyncio.run(
        _request(assets_module.create_app(), "GET", f"/assets/{digest}")
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == content
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_asset_liveness_and_readiness_use_distinct_http_semantics(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings
) -> None:
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)
    app = assets_module.create_app()

    live = asyncio.run(_request(app, "GET", "/livez"))
    ready = asyncio.run(_request(app, "GET", "/readyz"))
    asset_settings.asset_root.rmdir()
    unavailable = asyncio.run(_request(app, "GET", "/readyz"))

    assert live.status_code == HTTPStatus.OK
    assert live.json()["status"] == "alive"
    assert ready.status_code == HTTPStatus.OK
    assert ready.json()["status"] == "ready"
    assert unavailable.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert unavailable.json()["status"] == "not-ready"


def test_asset_server_refuses_missing_digest_path(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings
) -> None:
    digest = hashlib.sha256(b"missing content").hexdigest()
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)

    response = asyncio.run(
        _request(assets_module.create_app(), "GET", f"/assets/{digest}")
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["detail"] == {
        "code": "ASSET_NOT_FOUND",
        "retryable": False,
    }


def test_asset_server_refuses_file_over_configured_size_limit(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings
) -> None:
    content = b"too large"
    digest = hashlib.sha256(content).hexdigest()
    path = asset_settings.asset_root / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    asset_settings.max_asset_bytes = len(content) - 1
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)

    response = asyncio.run(
        _request(assets_module.create_app(), "GET", f"/assets/{digest}")
    )

    assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert response.json()["detail"] == {
        "code": "ASSET_TOO_LARGE",
        "retryable": False,
    }


def test_asset_server_refuses_bytes_that_do_not_match_requested_digest(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings
) -> None:
    claimed_digest = hashlib.sha256(b"claimed content").hexdigest()
    path = asset_settings.asset_root / claimed_digest[:2] / claimed_digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"tampered content")
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)

    response = asyncio.run(
        _request(assets_module.create_app(), "GET", f"/assets/{claimed_digest}")
    )

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["detail"] == {
        "code": "ASSET_DIGEST_MISMATCH",
        "retryable": False,
    }


def test_asset_server_refuses_final_symlink_even_when_target_stays_inside_root(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings
) -> None:
    content = b"target bytes"
    digest = hashlib.sha256(content).hexdigest()
    actual = asset_settings.asset_root / "actual-file"
    actual.write_bytes(content)
    linked = asset_settings.asset_root / digest[:2] / digest
    linked.parent.mkdir(parents=True, exist_ok=True)
    linked.symlink_to(actual)
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)

    response = asyncio.run(
        _request(assets_module.create_app(), "GET", f"/assets/{digest}")
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["detail"] == {
        "code": "ASSET_NOT_FOUND",
        "retryable": False,
    }


def test_asset_server_refuses_digest_named_fifo_without_blocking(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings
) -> None:
    digest = hashlib.sha256(b"fifo content is never an asset").hexdigest()
    path = asset_settings.asset_root / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(path, mode=0o600)
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)

    response = asyncio.run(
        _request(assets_module.create_app(), "GET", f"/assets/{digest}")
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["detail"] == {
        "code": "ASSET_NOT_FOUND",
        "retryable": False,
    }


def test_asset_server_streams_verified_snapshot_after_path_replacement(
    monkeypatch: pytest.MonkeyPatch, asset_settings: RuntimeSettings, tmp_path: Path
) -> None:
    content = b"verified bytes must survive a post-check path replacement"
    replacement = b"replacement bytes must never be served"
    digest = hashlib.sha256(content).hexdigest()
    path = asset_settings.asset_root / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    outside = tmp_path / "replacement"
    outside.write_bytes(replacement)
    original_snapshot = assets_module._snapshot_asset

    def snapshot_then_replace(*args: Any, **kwargs: Any) -> tuple[Any, int]:
        snapshot, size = original_snapshot(*args, **kwargs)
        path.unlink()
        path.symlink_to(outside)
        return snapshot, size

    monkeypatch.setattr(assets_module, "_snapshot_asset", snapshot_then_replace)
    monkeypatch.setattr(assets_module, "load_settings", lambda _role: asset_settings)

    response = asyncio.run(
        _request(assets_module.create_app(), "GET", f"/assets/{digest}")
    )

    assert response.status_code == HTTPStatus.OK
    assert response.content == content
    assert replacement not in response.content


def test_product_state_type_cannot_claim_support_or_production() -> None:
    assert ProductState().model_dump(mode="json") == {
        "contract_version": "1",
        "production_state": "not-yet-in-production",
        "analysis_jobs_supported": False,
        "reason_code": "PIPELINE_NOT_IMPLEMENTED",
    }

    with pytest.raises(ValidationError):
        ProductState(production_state="production")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ProductState(analysis_jobs_supported=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ProductState(fabricated=True)  # type: ignore[call-arg]


def test_status_endpoint_reports_honest_state_and_no_job_intake(
    monkeypatch: pytest.MonkeyPatch, api_settings: RuntimeSettings
) -> None:
    monkeypatch.setattr(api_module, "load_settings", lambda _role: api_settings)

    app = api_module.create_app()
    status_response = asyncio.run(_request(app, "GET", "/v1/status"))
    unsupported_intake = asyncio.run(_request(app, "POST", "/v1/jobs", json_body={}))

    assert status_response.status_code == HTTPStatus.OK
    assert status_response.json() == ProductState().model_dump(mode="json")
    assert unsupported_intake.status_code in {
        HTTPStatus.NOT_FOUND,
        HTTPStatus.METHOD_NOT_ALLOWED,
    }
