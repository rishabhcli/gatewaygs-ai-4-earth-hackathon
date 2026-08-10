"""Adversarial unit tests for local-only development runtime boundaries."""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from scripts import dev_secrets, init_object_store, probe_infra, run_compose_service

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

EXPECTED_ENSURE_MESSAGE_COUNT = 2
EXPECTED_SECRET_WRITE_CLOSED_DESCRIPTORS = 2
EARLY_COMPOSE_EXIT_CODE = 7


def _runtime_root(tmp_path: Path) -> Path:
    root = tmp_path / "runtime-root"
    (root / ".dev" / "secrets").mkdir(parents=True)
    return root


def _write_secret(root: Path, name: str, value: str = "x" * 48) -> Path:
    path = root / ".dev" / "secrets" / name
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(dev_secrets.SECRET_FILE_MODE)
    return path


def test_secret_write_is_exclusive_durable_and_mode_restricted(tmp_path: Path) -> None:
    path = tmp_path / "secret"

    dev_secrets._write_new_secret(path, "s" * 48)

    assert path.read_text(encoding="utf-8") == "s" * 48 + "\n"
    assert stat.S_IMODE(path.stat().st_mode) == dev_secrets.SECRET_FILE_MODE
    dev_secrets._validate_existing_secret(path)
    with pytest.raises(FileExistsError):
        dev_secrets._write_new_secret(path, "replacement")


def test_secret_write_closes_descriptor_after_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "secret"
    real_close = os.close
    closed: list[int] = []

    def fail_write(_descriptor: int, _data: bytes) -> int:
        raise OSError("disk full")

    def record_close(descriptor: int) -> None:
        closed.append(descriptor)
        real_close(descriptor)

    monkeypatch.setattr("scripts.dev_secrets.os.write", fail_write)
    monkeypatch.setattr("scripts.dev_secrets.os.close", record_close)

    with pytest.raises(OSError, match="disk full"):
        dev_secrets._write_new_secret(path, "value")
    assert len(closed) == EXPECTED_SECRET_WRITE_CLOSED_DESCRIPTORS


@pytest.mark.parametrize(
    "failure",
    ["symlink", "directory", "permissions", "short", "oversize", "fifo", "utf8"],
)
def test_existing_secret_refuses_unsafe_files(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "secret"
    if failure == "symlink":
        target = tmp_path / "target"
        target.write_text("x" * 48, encoding="utf-8")
        target.chmod(0o600)
        path.symlink_to(target)
        match = "symlink"
    elif failure == "directory":
        path.mkdir()
        match = "regular file"
    elif failure == "fifo":
        os.mkfifo(path)
        match = "regular file"
    elif failure == "oversize":
        path.write_bytes(b"x" * (dev_secrets.MAXIMUM_SECRET_BYTES + 1))
        path.chmod(0o600)
        match = "exceeds 4096"
    elif failure == "utf8":
        path.write_bytes(b"\xff" * 48)
        path.chmod(0o600)
        match = "UTF-8"
    else:
        path.write_text("short" if failure == "short" else "x" * 48, encoding="utf-8")
        path.chmod(0o644 if failure == "permissions" else 0o600)
        match = "0600" if failure == "permissions" else "shorter"

    with pytest.raises(RuntimeError, match=match):
        dev_secrets._validate_existing_secret(path)


def test_existing_secret_swap_to_symlink_is_refused_on_the_opened_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "secret"
    path.write_text("x" * 48, encoding="utf-8")
    path.chmod(0o600)
    replacement = tmp_path / "replacement"
    replacement.write_text("y" * 48, encoding="utf-8")
    replacement.chmod(0o600)
    real_open = os.open
    swapped = False

    def swap_before_file_open(
        target: Any, flags: int, *args: Any, **kwargs: Any
    ) -> int:
        nonlocal swapped
        if target == path.name and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            path.unlink()
            path.symlink_to(replacement)
        return real_open(target, flags, *args, **kwargs)

    monkeypatch.setattr("scripts.dev_secrets.os.open", swap_before_file_open)
    with pytest.raises(RuntimeError, match="symlink"):
        dev_secrets._validate_existing_secret(path)
    assert replacement.read_text(encoding="utf-8") == "y" * 48


def test_secret_ensure_is_idempotent_and_never_rotates_existing_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / dev_secrets.REPOSITORY_NAME
    root.mkdir()
    monkeypatch.setattr(dev_secrets, "repository_root", lambda: root)
    monkeypatch.setattr(
        "scripts.dev_secrets.secrets.token_urlsafe", lambda _size: "u" * 64
    )
    monkeypatch.setattr("scripts.dev_secrets.secrets.token_hex", lambda _size: "a" * 32)

    dev_secrets.ensure()
    secrets_root = root / ".dev" / "secrets"
    first = {path.name: path.read_bytes() for path in secrets_root.iterdir()}
    dev_secrets.ensure()

    assert {path.name: path.read_bytes() for path in secrets_root.iterdir()} == first
    assert (
        stat.S_IMODE(secrets_root.stat().st_mode) == dev_secrets.SECRETS_DIRECTORY_MODE
    )
    assert all(
        stat.S_IMODE(path.stat().st_mode) == dev_secrets.SECRET_FILE_MODE
        for path in secrets_root.iterdir()
    )
    assert (
        capsys.readouterr().out.count("development secret files")
        == EXPECTED_ENSURE_MESSAGE_COUNT
    )


@pytest.mark.parametrize("redirect", [".dev", ".dev/secrets"])
def test_secret_ensure_refuses_redirected_directories_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, redirect: str
) -> None:
    root = tmp_path / dev_secrets.REPOSITORY_NAME
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    if redirect == ".dev":
        (root / ".dev").symlink_to(outside, target_is_directory=True)
    else:
        (root / ".dev").mkdir()
        (root / ".dev" / "secrets").symlink_to(outside, target_is_directory=True)
    outside_mode = stat.S_IMODE(outside.stat().st_mode)
    monkeypatch.setattr(dev_secrets, "repository_root", lambda: root)

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        dev_secrets.ensure()

    assert list(outside.iterdir()) == []
    assert stat.S_IMODE(outside.stat().st_mode) == outside_mode


@pytest.mark.parametrize("invalid", [".dev", ".dev/secrets"])
def test_secret_ensure_refuses_non_directory_parents_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: str
) -> None:
    root = tmp_path / dev_secrets.REPOSITORY_NAME
    root.mkdir()
    path = root / invalid
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(dev_secrets, "repository_root", lambda: root)

    with pytest.raises(RuntimeError, match="not a directory"):
        dev_secrets.ensure()


def test_secret_repository_identity_and_cli_dispatch_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_script = tmp_path / "foreign" / "scripts" / "dev_secrets.py"
    monkeypatch.setattr(dev_secrets, "__file__", str(fake_script))
    with pytest.raises(RuntimeError, match="identity"):
        dev_secrets.repository_root()

    called: list[bool] = []
    monkeypatch.setattr(
        dev_secrets, "parse_args", lambda: SimpleNamespace(command="ensure")
    )
    monkeypatch.setattr(dev_secrets, "ensure", lambda: called.append(True))
    dev_secrets.main()
    assert called == [True]


def test_object_store_secret_reader_enforces_trust_boundary(tmp_path: Path) -> None:
    root = _runtime_root(tmp_path)
    valid = _write_secret(root, "valid")
    assert init_object_store._read_secret(root, "valid") == "x" * 48

    valid.unlink()
    target = tmp_path / "outside-secret"
    target.write_text("x" * 48, encoding="utf-8")
    valid.symlink_to(target)
    with pytest.raises(RuntimeError, match="symlink"):
        init_object_store._read_secret(root, "valid")

    escaped = root / "outside"
    escaped.write_text("x" * 48, encoding="utf-8")
    with pytest.raises(RuntimeError, match="trust boundary"):
        init_object_store._read_secret(root, "../../outside")

    short = _write_secret(root, "short", "tiny")
    with pytest.raises(RuntimeError, match="invalid"):
        init_object_store._read_secret(root, short.name)

    insecure = _write_secret(root, "insecure")
    insecure.chmod(0o644)
    with pytest.raises(RuntimeError, match="0600"):
        init_object_store._read_secret(root, insecure.name)

    oversized = _write_secret(root, "oversized")
    oversized.write_bytes(b"x" * (init_object_store.MAXIMUM_SECRET_BYTES + 1))
    with pytest.raises(RuntimeError, match="exceeds 4096"):
        init_object_store._read_secret(root, oversized.name)

    fifo = root / ".dev" / "secrets" / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(RuntimeError, match="regular file"):
        init_object_store._read_secret(root, fifo.name)


def test_object_store_secret_swap_to_symlink_is_refused_on_the_opened_fd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _runtime_root(tmp_path)
    path = _write_secret(root, "valid")
    replacement = tmp_path / "replacement"
    replacement.write_text("y" * 48, encoding="utf-8")
    replacement.chmod(0o600)
    real_open = os.open
    swapped = False

    def swap_before_file_open(
        target: Any, flags: int, *args: Any, **kwargs: Any
    ) -> int:
        nonlocal swapped
        if target == path.name and kwargs.get("dir_fd") is not None and not swapped:
            swapped = True
            path.unlink()
            path.symlink_to(replacement)
        return real_open(target, flags, *args, **kwargs)

    monkeypatch.setattr("scripts.init_object_store.os.open", swap_before_file_open)
    with pytest.raises(RuntimeError, match="symlink"):
        init_object_store._read_secret(root, path.name)


@pytest.mark.parametrize("redirect", [".dev", ".dev/secrets"])
def test_object_store_reader_refuses_redirected_parent_directories(
    tmp_path: Path, redirect: str
) -> None:
    root = tmp_path / "runtime-root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if redirect == ".dev":
        secrets = outside / "secrets"
        secrets.mkdir()
        (root / ".dev").symlink_to(outside, target_is_directory=True)
    else:
        secrets = outside
        (root / ".dev").mkdir()
        (root / ".dev" / "secrets").symlink_to(secrets, target_is_directory=True)
    target = secrets / "valid"
    target.write_text("x" * 48, encoding="utf-8")
    target.chmod(0o600)

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        init_object_store._read_secret(root, target.name)


def test_object_store_client_uses_only_repository_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _runtime_root(tmp_path)
    _write_secret(root, "minio_root_user", "u" * 48)
    _write_secret(root, "minio_root_password", "p" * 48)
    sentinel = object()
    constructor = MagicMock(return_value=sentinel)
    monkeypatch.setattr(init_object_store, "Minio", constructor)

    assert init_object_store.client(root) is sentinel
    constructor.assert_called_once_with(
        init_object_store.ENDPOINT,
        access_key="u" * 48,
        secret_key="p" * 48,
        secure=False,
    )


def test_object_bucket_creation_and_existing_bucket_are_idempotent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    object_store = MagicMock()
    object_store.bucket_exists.side_effect = [False, True]
    monkeypatch.setattr(init_object_store, "client", lambda _root: object_store)

    init_object_store.ensure_bucket(timeout_seconds=1)

    object_store.make_bucket.assert_called_once_with(init_object_store.BUCKET)
    assert "object bucket is ready" in capsys.readouterr().out

    existing = MagicMock()
    existing.bucket_exists.return_value = True
    monkeypatch.setattr(init_object_store, "client", lambda _root: existing)
    init_object_store.ensure_bucket(timeout_seconds=1)
    existing.make_bucket.assert_not_called()


def test_object_bucket_timeout_preserves_root_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_store = MagicMock()
    root_error = OSError("endpoint unavailable")
    object_store.bucket_exists.side_effect = root_error
    ticks = iter((0.0, 0.1, 1.0))
    monkeypatch.setattr(init_object_store, "client", lambda _root: object_store)
    monkeypatch.setattr("scripts.init_object_store.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("scripts.init_object_store.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="before timeout") as caught:
        init_object_store.ensure_bucket(timeout_seconds=0.5)
    assert caught.value.__cause__ is root_error


def test_object_bucket_repository_identity_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_script = tmp_path / "foreign" / "scripts" / "init_object_store.py"
    monkeypatch.setattr(init_object_store, "__file__", str(fake_script))
    with pytest.raises(RuntimeError, match="identity"):
        init_object_store.ensure_bucket(timeout_seconds=0)


def _postgis_cursor(monkeypatch: pytest.MonkeyPatch, row: object) -> MagicMock:
    target = MagicMock()
    target.dsn.return_value.get_secret_value.return_value = "postgresql://local"
    monkeypatch.setattr(probe_infra, "DatabaseTarget", lambda: target)
    cursor = MagicMock()
    cursor.fetchone.return_value = row
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor_context
    monkeypatch.setattr(
        "scripts.probe_infra.psycopg.connect", MagicMock(return_value=connection)
    )
    return cursor


def test_postgis_probe_executes_semantic_extension_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cursor = _postgis_cursor(monkeypatch, ("16.4", "3.5.2"))

    payload = probe_infra.probe_postgis(tmp_path)

    assert payload["status"] == "ready"
    assert payload["postgres_version"] == "16.4"
    assert payload["postgis_version"] == "3.5.2"
    cursor.execute.assert_called_once_with(
        "SELECT current_setting('server_version'), postgis_version()"
    )


@pytest.mark.parametrize("row", [None, ("16",), ("16", ""), (16, "3.5")])
def test_postgis_probe_refuses_invalid_query_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, row: object
) -> None:
    _postgis_cursor(monkeypatch, row)
    with pytest.raises(RuntimeError, match="invalid result"):
        probe_infra.probe_postgis(tmp_path)


def test_minio_probe_requires_repository_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    object_store = MagicMock()
    object_store.bucket_exists.return_value = False
    monkeypatch.setattr(probe_infra, "client", lambda _root: object_store)
    with pytest.raises(RuntimeError, match="does not exist"):
        probe_infra.probe_minio(tmp_path)

    object_store.bucket_exists.return_value = True
    assert probe_infra.probe_minio(tmp_path) == {
        "contract_version": "1",
        "service": "minio",
        "status": "ready",
        "bucket": init_object_store.BUCKET,
    }


@pytest.mark.parametrize("service", ["postgis", "minio"])
def test_infra_probe_cli_emits_bounded_success_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    service: str,
) -> None:
    expected = {"contract_version": "1", "service": service, "status": "ready"}
    monkeypatch.setattr(
        probe_infra, "parse_args", lambda: SimpleNamespace(service=service)
    )
    monkeypatch.setattr(probe_infra, "_root", lambda: tmp_path)
    monkeypatch.setattr(probe_infra, f"probe_{service}", lambda _root: expected)

    assert probe_infra.main() == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_infra_probe_cli_redacts_failure_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        probe_infra, "parse_args", lambda: SimpleNamespace(service="postgis")
    )
    monkeypatch.setattr(probe_infra, "_root", lambda: tmp_path)
    monkeypatch.setattr(
        probe_infra,
        "probe_postgis",
        MagicMock(side_effect=OSError("secret-token-must-not-leak")),
    )

    assert probe_infra.main() == 1
    output = capsys.readouterr().out
    assert "secret-token" not in output
    assert json.loads(output) == {
        "code": "POSTGIS_UNAVAILABLE",
        "contract_version": "1",
        "service": "postgis",
        "status": "not-ready",
    }


def test_infra_repository_identity_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_script = tmp_path / "foreign" / "scripts" / "probe_infra.py"
    monkeypatch.setattr(probe_infra, "__file__", str(fake_script))
    with pytest.raises(RuntimeError, match="identity"):
        probe_infra._root()


def test_compose_stop_is_scoped_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "ports.env").write_text("PORT_5=4175\n", encoding="utf-8")
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    completed: subprocess.CompletedProcess[bytes] = subprocess.CompletedProcess([], 0)
    runner = MagicMock(return_value=completed)
    monkeypatch.setattr("scripts.run_compose_service.subprocess.run", runner)

    run_compose_service.stop_service(tmp_path, "catalog")

    command = runner.call_args.args[0]
    prefix = run_compose_service.compose_prefix(tmp_path)
    assert command[: len(prefix)] == prefix
    assert command[-4:] == ["stop", "--timeout", "3", "catalog"]
    assert "down" not in command

    runner.return_value = subprocess.CompletedProcess([], 2)
    with pytest.raises(RuntimeError, match="scoped Compose stop"):
        run_compose_service.stop_service(tmp_path, "catalog")


def test_compose_run_refuses_foreign_project_before_spawning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "foreign-project")
    popen = MagicMock()
    monkeypatch.setattr("scripts.run_compose_service.subprocess.Popen", popen)
    with pytest.raises(RuntimeError, match="foreign"):
        run_compose_service.run("catalog")
    popen.assert_not_called()


@pytest.mark.parametrize(
    ("service", "expected_build_flag"),
    [("catalog", None), ("minio", "--build")],
)
def test_compose_run_constructs_allowlisted_foreground_command(
    monkeypatch: pytest.MonkeyPatch, service: str, expected_build_flag: str | None
) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", run_compose_service.PROJECT)
    monkeypatch.setenv("COMPOSE_FILE", "/foreign/compose.yaml")
    process = MagicMock()
    process.poll.return_value = EARLY_COMPOSE_EXIT_CODE
    popen = MagicMock(return_value=process)
    monkeypatch.setattr("scripts.run_compose_service.subprocess.Popen", popen)
    monkeypatch.setattr("scripts.run_compose_service.signal.signal", MagicMock())

    assert run_compose_service.run(service) == EARLY_COMPOSE_EXIT_CODE
    command = popen.call_args.args[0]
    assert command[-1] == service
    actual_build_flag = "--build" if "--build" in command else None
    assert actual_build_flag == expected_build_flag
    root = run_compose_service.repository_root()
    prefix = run_compose_service.compose_prefix(root)
    assert command[: len(prefix)] == prefix
    child_environment = popen.call_args.kwargs["env"]
    assert "COMPOSE_FILE" not in child_environment
    assert child_environment["COMPOSE_PROJECT_NAME"] == run_compose_service.PROJECT
    assert child_environment["DOCKER_CONFIG"] == str(
        root / ".dev" / "config" / "docker"
    )


def _signal_driven_process(
    handlers: dict[int, Callable[[int, object], None]], waits: list[object]
) -> MagicMock:
    process = MagicMock()
    poll_count = 0

    def poll() -> int | None:
        nonlocal poll_count
        poll_count += 1
        if poll_count == 1:
            handlers[signal.SIGTERM](signal.SIGTERM, object())
            return None
        return 0

    process.poll.side_effect = poll
    process.wait.side_effect = waits
    return process


def test_compose_signal_stops_only_selected_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", run_compose_service.PROJECT)
    handlers: dict[int, Callable[[int, object], None]] = {}
    monkeypatch.setattr(
        "scripts.run_compose_service.signal.signal",
        lambda number, handler: handlers.__setitem__(number, cast("Any", handler)),
    )
    process = _signal_driven_process(handlers, [0])
    monkeypatch.setattr(
        "scripts.run_compose_service.subprocess.Popen", lambda *_a, **_kw: process
    )
    monkeypatch.setattr("scripts.run_compose_service.time.sleep", lambda _seconds: None)
    stopper = MagicMock()
    monkeypatch.setattr(run_compose_service, "stop_service", stopper)

    assert run_compose_service.run("catalog") == 0
    stopper.assert_called_once()
    assert stopper.call_args.args[1] == "catalog"
    process.terminate.assert_not_called()
    process.kill.assert_not_called()


def test_compose_child_timeout_targets_only_owned_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", run_compose_service.PROJECT)
    handlers: dict[int, Callable[[int, object], None]] = {}
    monkeypatch.setattr(
        "scripts.run_compose_service.signal.signal",
        lambda number, handler: handlers.__setitem__(number, cast("Any", handler)),
    )
    timeout = subprocess.TimeoutExpired(["docker"], 5)
    process = _signal_driven_process(handlers, [timeout, 0])
    monkeypatch.setattr(
        "scripts.run_compose_service.subprocess.Popen", lambda *_a, **_kw: process
    )
    monkeypatch.setattr("scripts.run_compose_service.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(run_compose_service, "stop_service", MagicMock())

    assert run_compose_service.run("minio") == 0
    process.terminate.assert_called_once_with()
    process.kill.assert_not_called()


def test_compose_finally_escalates_only_after_owned_child_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", run_compose_service.PROJECT)
    handlers: dict[int, Callable[[int, object], None]] = {}
    monkeypatch.setattr(
        "scripts.run_compose_service.signal.signal",
        lambda number, handler: handlers.__setitem__(number, cast("Any", handler)),
    )
    timeout = subprocess.TimeoutExpired(["docker"], 5)
    process = _signal_driven_process(handlers, [timeout, 0])
    poll_calls = 0

    def poll_for_cleanup() -> None:
        nonlocal poll_calls
        poll_calls += 1
        if poll_calls == 1:
            handlers[signal.SIGTERM](signal.SIGTERM, object())

    process.poll.side_effect = poll_for_cleanup
    monkeypatch.setattr(
        "scripts.run_compose_service.subprocess.Popen", lambda *_a, **_kw: process
    )
    monkeypatch.setattr("scripts.run_compose_service.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        run_compose_service,
        "stop_service",
        MagicMock(side_effect=RuntimeError("stop failed")),
    )

    with pytest.raises(RuntimeError, match="stop failed"):
        run_compose_service.run("catalog")
    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()


def test_compose_repository_identity_and_main_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_script = tmp_path / "foreign" / "scripts" / "run_compose_service.py"
    monkeypatch.setattr(run_compose_service, "__file__", str(fake_script))
    with pytest.raises(RuntimeError, match="identity"):
        run_compose_service.repository_root()

    monkeypatch.setattr(
        run_compose_service, "parse_args", lambda: SimpleNamespace(service="catalog")
    )
    monkeypatch.setattr(
        run_compose_service, "run", lambda service: 0 if service == "catalog" else 1
    )
    assert run_compose_service.main() == 0
