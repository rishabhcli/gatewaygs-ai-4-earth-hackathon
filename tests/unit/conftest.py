"""Unit-test fixtures for fail-closed service boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from services.runtime.config import DatabaseTarget, RuntimeSettings, ServiceRole

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def repository_root(tmp_path: Path) -> Path:
    """Create the exact repository shape required by ``RuntimeSettings``."""

    root = tmp_path / "gatewaygs-ai-4-earth-hackathon"
    (root / ".dev" / "secrets").mkdir(parents=True)
    (root / ".dev" / "assets").mkdir(parents=True)
    password_file = root / ".dev" / "secrets" / "postgres_password"
    password_file.write_text(
        "unit-test-only-password-with-32-characters",
        encoding="utf-8",
    )
    password_file.chmod(0o600)
    return root


@pytest.fixture
def api_settings(repository_root: Path) -> RuntimeSettings:
    return RuntimeSettings(
        role=ServiceRole.API,
        host="127.0.0.1",
        port=4170,
        repository_root=repository_root,
        database=DatabaseTarget(),
        dependency_timeout_seconds=0.1,
        asset_root=repository_root / ".dev" / "assets",
    )


@pytest.fixture
def asset_settings(repository_root: Path) -> RuntimeSettings:
    return RuntimeSettings(
        role=ServiceRole.ASSET_SERVER,
        host="127.0.0.1",
        port=4173,
        repository_root=repository_root,
        database=DatabaseTarget(),
        dependency_timeout_seconds=0.1,
        asset_root=repository_root / ".dev" / "assets",
    )


@pytest.fixture
def worker_settings(repository_root: Path) -> RuntimeSettings:
    return RuntimeSettings(
        role=ServiceRole.WORKER_HEALTH,
        host="127.0.0.1",
        port=4172,
        repository_root=repository_root,
        database=DatabaseTarget(),
        dependency_timeout_seconds=0.1,
        asset_root=repository_root / ".dev" / "assets",
    )
