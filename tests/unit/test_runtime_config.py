"""Startup configuration and secret-file boundary tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import pytest
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

from services.runtime.config import (
    EXPECTED_PORTS,
    DatabaseTarget,
    RuntimeSettings,
    ServiceRole,
    load_settings,
)

_PORT_BLOCK_MIN = 4170
_PORT_BLOCK_MAX = 4179
_TUNED_DEPENDENCY_TIMEOUT_SECONDS = 2.5
_TUNED_MAX_ASSET_BYTES = 1_048_576


def test_nested_database_contract_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DatabaseTarget(fabricated=True)  # type: ignore[call-arg]


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _runtime_settings(
    repository_root: Path,
    *,
    role: ServiceRole = ServiceRole.API,
    port: int = 4170,
    host: Literal["127.0.0.1"] = "127.0.0.1",
    asset_root: Path = Path(".dev/assets"),
) -> RuntimeSettings:
    return RuntimeSettings(
        role=role,
        host=host,
        port=port,
        repository_root=repository_root,
        asset_root=asset_root,
    )


@pytest.mark.parametrize(
    ("role", "wrong_port"),
    [
        (ServiceRole.API, 4171),
        (ServiceRole.WORKER_HEALTH, 4170),
        (ServiceRole.ASSET_SERVER, 4179),
    ],
)
def test_role_refuses_another_service_port(
    repository_root: Path, role: ServiceRole, wrong_port: int
) -> None:
    with pytest.raises(ValidationError, match="must use repository-owned port"):
        _runtime_settings(repository_root, role=role, port=wrong_port)


@hypothesis_settings(
    max_examples=128,
    derandomize=True,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(
    port=st.integers(min_value=-(2**31), max_value=(2**31) - 1).filter(
        lambda candidate: candidate < _PORT_BLOCK_MIN or candidate > _PORT_BLOCK_MAX
    )
)
def test_property_ports_outside_owned_block_are_always_refused(
    repository_root: Path, port: int
) -> None:
    """Property cases: 128 integers outside ports 4170-4179 are refused."""

    with pytest.raises(ValidationError):
        _runtime_settings(repository_root, port=port)


@hypothesis_settings(
    max_examples=3,
    derandomize=True,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(role=st.sampled_from(tuple(ServiceRole)))
def test_property_each_service_role_accepts_only_its_declared_port(
    repository_root: Path, role: ServiceRole
) -> None:
    """Property cases: 3 roles, each bound to exactly its owned port."""

    configured = _runtime_settings(
        repository_root,
        role=role,
        port=EXPECTED_PORTS[role],
    )
    assert configured.port == EXPECTED_PORTS[role]


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "::", "localhost", "127.0.0.2"],  # noqa: S104
)
def test_runtime_refuses_non_loopback_or_ambiguous_host(
    repository_root: Path, host: str
) -> None:
    with pytest.raises(ValidationError):
        _runtime_settings(repository_root, host=host)  # type: ignore[arg-type]


def test_runtime_normalizes_an_asset_path_beneath_repository_dev(
    repository_root: Path,
) -> None:
    configured = _runtime_settings(repository_root, asset_root=Path(".dev/assets"))

    assert configured.asset_root == (repository_root / ".dev" / "assets").resolve()
    assert configured.asset_root.is_absolute()


@pytest.mark.parametrize(
    "asset_path",
    [Path("../outside"), Path("assets"), Path(".devil/assets")],
)
def test_runtime_refuses_asset_paths_outside_repository_dev(
    repository_root: Path, asset_path: Path
) -> None:
    with pytest.raises(ValidationError, match="asset_root must remain"):
        _runtime_settings(repository_root, asset_root=asset_path)


def test_runtime_refuses_asset_path_that_escapes_through_symlink(
    repository_root: Path,
) -> None:
    outside = repository_root.parent / "outside-assets"
    outside.mkdir()
    (repository_root / ".dev" / "linked-assets").symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(ValidationError, match="asset_root must remain"):
        _runtime_settings(
            repository_root,
            asset_root=repository_root / ".dev" / "linked-assets",
        )


def test_runtime_refuses_a_different_repository_root(tmp_path: Path) -> None:
    wrong_root = tmp_path / "another-repository"
    wrong_root.mkdir()

    with pytest.raises(ValidationError, match="does not identify this repository"):
        _runtime_settings(wrong_root)


def test_load_settings_refuses_environment_role_or_port(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    monkeypatch.chdir(repository_root)
    monkeypatch.setenv("GATEWAYGS_ROLE", ServiceRole.ASSET_SERVER.value)
    monkeypatch.setenv("GATEWAYGS_PORT", "4179")

    with pytest.raises(ValueError, match="unsupported runtime environment"):
        load_settings(ServiceRole.API)


def test_load_settings_refuses_environment_host_override(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    monkeypatch.chdir(repository_root)
    monkeypatch.setenv("GATEWAYGS_HOST", "0.0.0.0")  # noqa: S104

    with pytest.raises(ValueError, match="unsupported runtime environment"):
        load_settings(ServiceRole.API)


def test_load_settings_refuses_object_store_readiness_ssrf_override(
    monkeypatch: pytest.MonkeyPatch, repository_root: Path
) -> None:
    monkeypatch.chdir(repository_root)
    monkeypatch.setenv(
        "GATEWAYGS_OBJECT_STORE_READY_URL",
        "https://metadata.example.invalid/latest/credentials",
    )

    with pytest.raises(ValueError, match="unsupported runtime environment"):
        load_settings(ServiceRole.API)


def test_load_settings_refuses_same_named_foreign_repository_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    foreign_root = tmp_path / "gatewaygs-ai-4-earth-hackathon"
    foreign_root.mkdir()
    monkeypatch.setenv("GATEWAYGS_REPOSITORY_ROOT", str(foreign_root))

    with pytest.raises(ValueError, match="unsupported runtime environment"):
        load_settings(ServiceRole.ASSET_SERVER)


def test_load_settings_refuses_asset_root_redirect_inside_development_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GATEWAYGS_ASSET_ROOT", ".dev/secrets")

    with pytest.raises(ValueError, match="unsupported runtime environment"):
        load_settings(ServiceRole.ASSET_SERVER)


def test_load_settings_accepts_only_documented_bounded_tuning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GATEWAYGS_DEPENDENCY_TIMEOUT_SECONDS",
        str(_TUNED_DEPENDENCY_TIMEOUT_SECONDS),
    )
    monkeypatch.setenv("GATEWAYGS_MAX_ASSET_BYTES", str(_TUNED_MAX_ASSET_BYTES))

    configured = load_settings(ServiceRole.ASSET_SERVER)

    assert configured.dependency_timeout_seconds == _TUNED_DEPENDENCY_TIMEOUT_SECONDS
    assert configured.max_asset_bytes == _TUNED_MAX_ASSET_BYTES


def test_password_file_must_be_contained_by_secret_directory(
    repository_root: Path,
) -> None:
    outside = repository_root / ".dev" / "outside-password"
    outside.write_text("x" * 64, encoding="utf-8")
    target = DatabaseTarget(password_file=Path(".dev/outside-password"))

    with pytest.raises(ValueError, match=r"must remain under \.dev/secrets"):
        target.password(repository_root)


def test_password_file_cannot_escape_through_symlink(repository_root: Path) -> None:
    outside = repository_root / ".dev" / "outside-password"
    outside.write_text("x" * 64, encoding="utf-8")
    linked = repository_root / ".dev" / "secrets" / "linked-password"
    linked.symlink_to(outside)
    target = DatabaseTarget(password_file=linked)

    with pytest.raises(ValueError, match="must not be a symlink"):
        target.password(repository_root)


def test_password_file_refuses_symlinked_development_directory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "gatewaygs-ai-4-earth-hackathon"
    root.mkdir()
    outside = tmp_path / "outside-development-state"
    (outside / "secrets").mkdir(parents=True)
    (outside / "secrets" / "postgres_password").write_text("x" * 64, encoding="utf-8")
    (root / ".dev").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="state directory must not be a symlink"):
        DatabaseTarget().password(root)


def test_password_file_refuses_symlinked_secret_directory(
    repository_root: Path, tmp_path: Path
) -> None:
    declared = repository_root / ".dev" / "secrets"
    for path in declared.iterdir():
        path.unlink()
    declared.rmdir()
    outside = tmp_path / "outside-secrets"
    outside.mkdir()
    (outside / "postgres_password").write_text("x" * 64, encoding="utf-8")
    declared.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="secret directory must not be a symlink"):
        DatabaseTarget().password(repository_root)


def test_password_file_refuses_permissive_permissions(repository_root: Path) -> None:
    secret_file = repository_root / ".dev" / "secrets" / "permissive-password"
    secret_file.write_text("x" * 64, encoding="utf-8")
    secret_file.chmod(0o644)

    with pytest.raises(ValueError, match="permissions must be 0600"):
        DatabaseTarget(password_file=secret_file).password(repository_root)


def test_password_file_refuses_non_regular_path(repository_root: Path) -> None:
    secret_directory = repository_root / ".dev" / "secrets" / "not-a-file"
    secret_directory.mkdir()

    with pytest.raises(ValueError, match="must be a regular file"):
        DatabaseTarget(password_file=secret_directory).password(repository_root)


def test_password_file_refuses_fifo_without_blocking(repository_root: Path) -> None:
    secret_fifo = repository_root / ".dev" / "secrets" / "password-fifo"
    os.mkfifo(secret_fifo, mode=0o600)

    with pytest.raises(ValueError, match="must be a regular file"):
        DatabaseTarget(password_file=secret_fifo).password(repository_root)


def test_password_file_refuses_oversized_value(repository_root: Path) -> None:
    secret_file = repository_root / ".dev" / "secrets" / "oversized-password"
    _write_secret(secret_file, "x" * 4097)

    with pytest.raises(ValueError, match="exceeds 4096 bytes"):
        DatabaseTarget(password_file=secret_file).password(repository_root)


@pytest.mark.parametrize("length", [0, 1, 16, 30, 31])
def test_password_file_refuses_trimmed_values_shorter_than_32_characters(
    repository_root: Path, length: int
) -> None:
    secret_file = repository_root / ".dev" / "secrets" / "short-password"
    _write_secret(secret_file, ("x" * length) + "\n")
    target = DatabaseTarget(password_file=secret_file)

    with pytest.raises(ValueError, match="at least 32 characters"):
        target.password(repository_root)


def test_password_file_accepts_exact_minimum_and_keeps_value_secret(
    repository_root: Path,
) -> None:
    raw_secret = "x" * 32
    secret_file = repository_root / ".dev" / "secrets" / "minimum-password"
    _write_secret(secret_file, raw_secret + "\n")
    target = DatabaseTarget(password_file=secret_file)

    loaded = target.password(repository_root)

    assert loaded.get_secret_value() == raw_secret
    assert raw_secret not in str(loaded)
    assert raw_secret not in repr(loaded)


def test_dsn_percent_encodes_password_and_masks_its_representation(
    repository_root: Path,
) -> None:
    raw_secret = "a" * 32 + ":/@?%#"
    secret_file = repository_root / ".dev" / "secrets" / "reserved-password"
    _write_secret(secret_file, raw_secret)
    target = DatabaseTarget(password_file=secret_file)

    dsn = target.dsn(repository_root)

    assert raw_secret not in dsn.get_secret_value()
    assert "%3A%2F%40%3F%25%23" in dsn.get_secret_value()
    assert raw_secret not in str(dsn)
    assert raw_secret not in repr(dsn)
