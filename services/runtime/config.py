"""Typed, fail-closed configuration for local and deployed services."""

from __future__ import annotations

import os
import stat
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceRole(StrEnum):
    """Processes with independently enforced port ownership."""

    API = "api"
    WORKER_HEALTH = "worker-health"
    ASSET_SERVER = "asset-server"


EXPECTED_PORTS: dict[ServiceRole, int] = {
    ServiceRole.API: 4170,
    ServiceRole.WORKER_HEALTH: 4172,
    ServiceRole.ASSET_SERVER: 4173,
}
MINIMUM_SECRET_CHARACTERS = 32
MAXIMUM_SECRET_BYTES = 4096
SECRET_FILE_MODE = 0o600


def _require_real_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    resolved = path.resolve(strict=True)
    if resolved != path or not resolved.is_dir():
        raise ValueError(f"{label} escaped the repository or is not a directory")
    return resolved


def _resolve_secret_file(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("postgres password file must not be a symlink")
    return path.resolve(strict=True)


def _read_secret_file(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("postgres password path must be a regular file")
        if stat.S_IMODE(metadata.st_mode) != SECRET_FILE_MODE:
            raise ValueError("postgres password file permissions must be 0600")
        encoded = os.read(descriptor, MAXIMUM_SECRET_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(encoded) > MAXIMUM_SECRET_BYTES:
        raise ValueError("postgres password file exceeds 4096 bytes")
    try:
        return encoded.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("postgres password file must contain UTF-8 text") from exc


class DatabaseTarget(BaseModel):
    """Non-secret database coordinates plus an out-of-band password file."""

    model_config = ConfigDict(extra="forbid")

    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: Literal[4175] = 4175
    database: Literal["gatewaygs_ai_4_earth_hackathon"] = (
        "gatewaygs_ai_4_earth_hackathon"
    )
    user: Literal["gatewaygs_ai_4_earth_hackathon"] = "gatewaygs_ai_4_earth_hackathon"
    password_file: Path = Path(".dev/secrets/postgres_password")

    def password(self, repository_root: Path) -> SecretStr:
        root = repository_root.resolve(strict=True)
        development_root = _require_real_directory(
            root / ".dev", "development state directory"
        )
        secrets_root = _require_real_directory(
            development_root / "secrets", "postgres secret directory"
        )

        path = self.password_file
        if not path.is_absolute():
            path = root / path
        resolved = _resolve_secret_file(path)
        if not resolved.is_relative_to(secrets_root):
            raise ValueError("postgres password file must remain under .dev/secrets")
        value = _read_secret_file(resolved)
        if len(value) < MINIMUM_SECRET_CHARACTERS:
            raise ValueError("postgres password must contain at least 32 characters")
        return SecretStr(value)

    def dsn(self, repository_root: Path) -> SecretStr:
        password = quote(self.password(repository_root).get_secret_value(), safe="")
        return SecretStr(
            f"postgresql://{self.user}:{password}@{self.host}:{self.port}/{self.database}"
        )


class RuntimeEnvironment(BaseSettings):
    """The complete, documented environment surface for local services."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAYGS_",
        extra="forbid",
        case_sensitive=False,
    )

    dependency_timeout_seconds: float = Field(default=1.5, gt=0, le=10)
    max_asset_bytes: int = Field(default=268_435_456, gt=0, le=1_073_741_824)


ALLOWED_RUNTIME_ENVIRONMENT = frozenset(
    {
        "GATEWAYGS_DEPENDENCY_TIMEOUT_SECONDS",
        "GATEWAYGS_MAX_ASSET_BYTES",
    }
)


class RuntimeSettings(BaseModel):
    """Validated process settings.

    The service role is injected by the app factory rather than trusted from the
    environment. A wrong host or port causes startup failure instead of a silent
    fallback to a framework default.
    """

    model_config = ConfigDict(extra="forbid")

    role: ServiceRole
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=4170, le=4179)
    repository_root: Path = Field(default_factory=Path.cwd)
    database: DatabaseTarget = Field(default_factory=DatabaseTarget)
    object_store_ready_url: Literal["http://127.0.0.1:4176/minio/health/ready"] = (
        "http://127.0.0.1:4176/minio/health/ready"
    )
    dependency_timeout_seconds: float = Field(default=1.5, gt=0, le=10)
    asset_root: Path = Path(".dev/assets")
    max_asset_bytes: int = Field(default=268_435_456, gt=0, le=1_073_741_824)

    @model_validator(mode="after")
    def validate_owned_port_and_paths(self) -> Self:
        expected = EXPECTED_PORTS[self.role]
        if self.port != expected:
            raise ValueError(
                f"{self.role.value} must use repository-owned port {expected}; "
                f"received {self.port}"
            )

        root = self.repository_root.resolve(strict=True)
        if root.name != "gatewaygs-ai-4-earth-hackathon":
            raise ValueError("repository_root does not identify this repository")
        object.__setattr__(self, "repository_root", root)

        asset_root = self.asset_root
        if not asset_root.is_absolute():
            asset_root = root / asset_root
        asset_root = asset_root.resolve(strict=False)
        if asset_root != root / ".dev" / "assets":
            raise ValueError("asset_root must remain at repository .dev/assets")
        object.__setattr__(self, "asset_root", asset_root)
        return self


def load_settings(role: ServiceRole) -> RuntimeSettings:
    """Load documented tuning only; ownership and network targets are code-owned."""

    unsupported = sorted(
        key
        for key in os.environ
        if key.upper().startswith("GATEWAYGS_")
        and key.upper() not in ALLOWED_RUNTIME_ENVIRONMENT
    )
    if unsupported:
        raise ValueError(
            "unsupported runtime environment variables: " + ", ".join(unsupported)
        )
    environment = RuntimeEnvironment()
    repository_root = Path(__file__).resolve().parents[2]
    return RuntimeSettings(
        role=role,
        host="127.0.0.1",
        port=EXPECTED_PORTS[role],
        repository_root=repository_root,
        dependency_timeout_seconds=environment.dependency_timeout_seconds,
        max_asset_bytes=environment.max_asset_bytes,
    )
