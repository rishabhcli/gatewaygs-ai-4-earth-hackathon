"""Content-addressed local asset boundary with traversal-safe reads."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import stat
import tempfile
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from services.runtime.config import ServiceRole, load_settings
from services.runtime.health import (
    CheckStatus,
    DependencyCheck,
    HealthResponse,
    HealthStatus,
)
from services.runtime.observability import install_request_logging

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from io import BufferedRandom
    from pathlib import Path


_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _asset_path(asset_root: Path, digest: str) -> Path:
    if _SHA256.fullmatch(digest) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "INVALID_CONTENT_DIGEST", "retryable": False},
        )
    declared_parent = asset_root / digest[:2]
    if declared_parent.is_symlink():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "ASSET_PATH_ESCAPE", "retryable": False},
        )
    parent = declared_parent.resolve(strict=False)
    if not parent.is_relative_to(asset_root):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "ASSET_PATH_ESCAPE", "retryable": False},
        )
    return parent / digest


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "ASSET_NOT_FOUND", "retryable": False},
    )


def _open_asset(path: Path) -> int:
    directory_flags = os.O_RDONLY | os.O_DIRECTORY
    file_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    try:
        parent_descriptor = os.open(path.parent, directory_flags)
    except OSError as exc:
        raise _not_found() from exc
    try:
        try:
            return os.open(path.name, file_flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise _not_found() from exc
    finally:
        os.close(parent_descriptor)


def _snapshot_asset(
    path: Path, expected_digest: str, maximum_bytes: int, asset_root: Path
) -> tuple[BufferedRandom, int]:
    descriptor = _open_asset(path)
    snapshot = tempfile.TemporaryFile(  # noqa: SIM115 - response owns this handle
        mode="w+b", dir=asset_root
    )
    try:
        size = _copy_verified_asset(
            descriptor, snapshot, expected_digest, maximum_bytes
        )
    except BaseException:
        snapshot.close()
        raise
    else:
        return snapshot, size
    finally:
        os.close(descriptor)


def _copy_verified_asset(
    descriptor: int,
    snapshot: BufferedRandom,
    expected_digest: str,
    maximum_bytes: int,
) -> int:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise _not_found()
    if metadata.st_size > maximum_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail={"code": "ASSET_TOO_LARGE", "retryable": False},
        )
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        size += len(chunk)
        if size > maximum_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={"code": "ASSET_TOO_LARGE", "retryable": False},
            )
        digest.update(chunk)
        snapshot.write(chunk)
    if not hmac.compare_digest(digest.hexdigest(), expected_digest):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ASSET_DIGEST_MISMATCH", "retryable": False},
        )
    snapshot.seek(0)
    return size


async def _stream_snapshot(snapshot: BufferedRandom) -> AsyncIterator[bytes]:
    try:
        while chunk := await asyncio.to_thread(snapshot.read, 1024 * 1024):
            yield chunk
    finally:
        snapshot.close()


def create_app() -> FastAPI:
    settings = load_settings(ServiceRole.ASSET_SERVER)
    settings.asset_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    app = FastAPI(
        title="Content-addressed scene asset server",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    install_request_logging(app, ServiceRole.ASSET_SERVER.value)

    @app.get("/livez", response_model=HealthResponse)
    async def livez() -> HealthResponse:
        return HealthResponse(service="asset-server", status=HealthStatus.ALIVE)

    @app.get("/readyz", response_model=HealthResponse)
    async def readyz(response: Response) -> HealthResponse:
        writable = settings.asset_root.is_dir() and os.access(
            settings.asset_root, os.R_OK | os.W_OK | os.X_OK
        )
        check = DependencyCheck(
            name="asset-root",
            status=CheckStatus.PASS if writable else CheckStatus.FAIL,
            code="ASSET_ROOT_READY" if writable else "ASSET_ROOT_UNAVAILABLE",
        )
        result = HealthResponse(
            service="asset-server",
            status=(
                HealthStatus.READY
                if check.status is CheckStatus.PASS
                else HealthStatus.NOT_READY
            ),
            checks=[check],
        )
        response.status_code = result.http_status
        return result

    @app.get("/assets/{digest}")
    async def get_asset(digest: str) -> StreamingResponse:
        path = _asset_path(settings.asset_root, digest)
        snapshot, size = await asyncio.to_thread(
            _snapshot_asset,
            path,
            digest,
            settings.max_asset_bytes,
            settings.asset_root,
        )
        return StreamingResponse(
            _stream_snapshot(snapshot),
            media_type="application/octet-stream",
            headers={
                "cache-control": "public, max-age=31536000, immutable",
                "content-length": str(size),
                "x-content-type-options": "nosniff",
            },
        )

    return app
