#!/usr/bin/env python3
"""Repository-scoped development process lifecycle.

``devctl`` deliberately contains no product-service implementation.  It reads the
checked-in ``dev-services.json`` and starts only the
foreground argv arrays declared there.  Missing or incomplete configuration is
an error, never a reason to create a fake readiness server.

Configuration schema (version 1)::

    {
        "version": 1,
        "services": [
            {
                "name": "api",
                "port_envs": ["PORT_0"],
                "command": ["python3", "-m", "service", "--port", "${PORT_0}"],
                "listener_ownership": "direct",
                "health": [
                    {
                        "port_env": "PORT_0",
                        "kind": "http-json",
                        "path": "/readyz",
                        "expect_status": 200,
                        "expect": {"service": "api", "status": "ready"},
                    }
                ],
            }
        ],
    }

A service may own multiple ports (for example, MinIO's API and console) and
has one readiness contract per port.  ``listener_ownership`` is ``direct`` by
default and requires the recorded foreground PID to own the socket.  Docker
published ports may explicitly use ``delegated``: the Docker holder is accepted
only when the exact repository-scoped Compose project reports the expected
running service and loopback publisher.  The Docker holder is never signalled;
only the foreground Compose PID launched by this program is stopped.  Every
command must remain in the foreground.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import stat
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

if TYPE_CHECKING:
    from collections.abc import (
        Callable,
        Iterable,
        Iterator,
        Mapping,
        Sequence,
        Set,
    )

PROJECT_NAME = "gatewaygs-ai-4-earth-hackathon"
BIND_HOST = "127.0.0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PORT_BLOCK = tuple(range(4170, 4180))
PORT_SPECS: dict[str, int] = {
    "PORT_0": 4170,
    "PORT_1": 4171,
    "PORT_2": 4172,
    "PORT_3": 4173,
    "PORT_5": 4175,
    "PORT_6": 4176,
    "PORT_7": 4177,
}
ALLOCATED_PORTS = frozenset(PORT_SPECS.values())
PROTECTED_ENV = frozenset(
    {
        "HOST",
        "BIND_HOST",
        "DEVCTL_HOST",
        "PORT",
        "PORTS",
        "COMPOSE_PROJECT_NAME",
        *PORT_SPECS,
    }
)
DEVCTL_TUNING_ENV = frozenset(
    {
        "DEVCTL_STARTUP_GRACE_SECONDS",
        "DEVCTL_SHUTDOWN_TIMEOUT_SECONDS",
        "DEVCTL_HEALTH_TIMEOUT_SECONDS",
        "DEVCTL_HEALTH_INTERVAL_SECONDS",
    }
)
CHILD_HOST_ENV = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "USER",
        "LOGNAME",
        "GATEWAYGS_DEPENDENCY_TIMEOUT_SECONDS",
        "GATEWAYGS_MAX_ASSET_BYTES",
    }
)
SERVICE_ENV_ALLOWLIST = frozenset(
    {
        "GATEWAYGS_DEPENDENCY_TIMEOUT_SECONDS",
        "GATEWAYGS_MAX_ASSET_BYTES",
    }
)
SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
PORT_LINE_RE = re.compile(r"^(PORT_[0-9]+)\s*=\s*([0-9]+)\s*$")
COMPOSE_CONFIG_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_HEALTH_BODY_BYTES = 64 * 1024
MIN_PROBE_TIMEOUT_SECONDS = 0.05
MAX_PROBE_TIMEOUT_SECONDS = 10.0
HTTP_SUCCESS_MIN = 200
HTTP_SUCCESS_MAX = 299
MIN_TEXT_MARKER_LENGTH = 8
LINUX_START_TICKS_INDEX = 19
DARWIN_PROC_PIDTBSDINFO = 3
DARWIN_ZOMBIE_STATUS = 5
MAX_COMPOSE_PS_BYTES = 256 * 1024
MAX_LSOF_OUTPUT_BYTES = 256 * 1024
MAX_TOOL_STDERR_BYTES = 64 * 1024
MAX_VERSION_OUTPUT_BYTES = 4 * 1024
MAX_PID_RECORD_BYTES = 16 * 1024
COMPOSE_HASH_FIELD_COUNT = 2
PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
MINIMUM_COMPOSE_VERSION = (2, 24, 0)
DELEGATED_COMPOSE_SERVICES: dict[
    str, tuple[str, frozenset[tuple[str, int, int, str]]]
] = {
    "postgis": (
        "catalog",
        frozenset({(BIND_HOST, 4175, 5432, "tcp")}),
    ),
    "minio": (
        "minio",
        frozenset(
            {
                (BIND_HOST, 4176, 9000, "tcp"),
                (BIND_HOST, 4177, 9001, "tcp"),
            }
        ),
    ),
}
DELEGATED_RECORD_BY_COMPOSE = {
    compose_service: record_service
    for record_service, (
        compose_service,
        _publishers,
    ) in DELEGATED_COMPOSE_SERVICES.items()
}


class DevctlError(RuntimeError):
    """A safe, user-facing lifecycle failure."""


def _read_private_pid_record(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DevctlError(f"cannot read PID record {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise DevctlError(f"PID record must be a regular file: {path}")
        if stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE:
            raise DevctlError(f"PID record permissions must be 0600: {path}")
        if metadata.st_size > MAX_PID_RECORD_BYTES:
            raise DevctlError(f"PID record exceeds size limit: {path}")
        encoded = os.read(descriptor, MAX_PID_RECORD_BYTES + 1)
        if len(encoded) > MAX_PID_RECORD_BYTES:
            raise DevctlError(f"PID record exceeds size limit: {path}")
        return encoded
    finally:
        os.close(descriptor)


def _open_private_service_log(path: Path, service: str) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, PRIVATE_FILE_MODE)
    except OSError as exc:
        raise DevctlError(f"cannot open service log for {service}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
    except OSError as exc:
        os.close(descriptor)
        raise DevctlError(f"cannot inspect service log for {service}: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise DevctlError(f"service log must be a regular file: {service}")
    try:
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        secured_mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
    except OSError as exc:
        os.close(descriptor)
        raise DevctlError(f"cannot secure service log for {service}: {exc}") from exc
    if secured_mode != PRIVATE_FILE_MODE:
        os.close(descriptor)
        raise DevctlError(f"service log permissions must be 0600: {service}")
    return descriptor


def _open_exclusive_private_file(path: Path, label: str) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, PRIVATE_FILE_MODE)
    except OSError as exc:
        raise DevctlError(f"cannot create private {label}") from exc
    try:
        metadata = os.fstat(descriptor)
    except OSError as exc:
        os.close(descriptor)
        with contextlib.suppress(OSError):
            path.unlink()
        raise DevctlError(f"cannot inspect private {label}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        with contextlib.suppress(OSError):
            path.unlink()
        raise DevctlError(f"private {label} must be a regular file")
    try:
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        secured_mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
    except OSError as exc:
        os.close(descriptor)
        with contextlib.suppress(OSError):
            path.unlink()
        raise DevctlError(f"cannot secure private {label}") from exc
    if secured_mode != PRIVATE_FILE_MODE:
        os.close(descriptor)
        with contextlib.suppress(OSError):
            path.unlink()
        raise DevctlError(f"private {label} permissions must be 0600")
    return descriptor


def _validated_delegated_container_id(
    ownership: object, value: object, source: Path
) -> str | None:
    if value is None:
        return None
    if (
        ownership != "delegated"
        or not isinstance(value, str)
        or CONTAINER_ID_RE.fullmatch(value) is None
    ):
        raise DevctlError(
            f"invalid delegated container identity in PID record: {source}"
        )
    return value


@dataclasses.dataclass(frozen=True)
class ProcessCaptureSpec:
    cwd: Path
    environment: Mapping[str, str] | None
    output_directory: Path
    timeout_seconds: float
    stdout_limit: int
    stderr_limit: int
    label: str


def _bounded_process_output(
    argv: Sequence[str], spec: ProcessCaptureSpec
) -> subprocess.CompletedProcess[str]:
    with (
        tempfile.TemporaryFile(mode="w+b", dir=spec.output_directory) as stdout_file,
        tempfile.TemporaryFile(mode="w+b", dir=spec.output_directory) as stderr_file,
    ):
        completed = subprocess.run(  # noqa: S603 -- caller supplies fixed argv
            list(argv),
            cwd=spec.cwd,
            env=spec.environment,
            check=False,
            stdout=stdout_file,
            stderr=stderr_file,
            timeout=spec.timeout_seconds,
        )
        captured_stdout = completed.stdout
        captured_stderr = completed.stderr
        if captured_stdout is None:
            if os.fstat(stdout_file.fileno()).st_size > spec.stdout_limit:
                raise DevctlError(f"{spec.label} stdout exceeded its byte limit")
            stdout_file.seek(0)
            stdout_bytes = stdout_file.read(spec.stdout_limit + 1)
        else:
            stdout_bytes = (
                captured_stdout.encode("utf-8")
                if isinstance(captured_stdout, str)
                else captured_stdout
            )
        if captured_stderr is None:
            if os.fstat(stderr_file.fileno()).st_size > spec.stderr_limit:
                raise DevctlError(f"{spec.label} stderr exceeded its byte limit")
            stderr_file.seek(0)
            stderr_bytes = stderr_file.read(spec.stderr_limit + 1)
        else:
            stderr_bytes = (
                captured_stderr.encode("utf-8")
                if isinstance(captured_stderr, str)
                else captured_stderr
            )
        if len(stdout_bytes) > spec.stdout_limit:
            raise DevctlError(f"{spec.label} stdout exceeded its byte limit")
        if len(stderr_bytes) > spec.stderr_limit:
            raise DevctlError(f"{spec.label} stderr exceeded its byte limit")
        try:
            stdout = stdout_bytes.decode("utf-8")
            stderr = stderr_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DevctlError(f"{spec.label} returned non-UTF-8 output") from exc
        return subprocess.CompletedProcess(
            args=argv,
            returncode=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )


@dataclasses.dataclass(frozen=True)
class Listener:
    port: int
    pid: int
    command: str
    endpoint: str


@dataclasses.dataclass(frozen=True)
class ComposeServiceRecord:
    container_id: str
    state: str
    name: str
    publishers: frozenset[tuple[str, int, int, str]]
    labels: Mapping[str, str]


@dataclasses.dataclass(frozen=True)
class HealthSpec:
    port_env: str
    kind: str
    path: str | None = None
    expect_status: int | None = None
    expect: Mapping[str, Any] | None = None
    expect_text: str | None = None
    expect_headers: Mapping[str, str] | None = None
    argv: tuple[str, ...] = ()
    timeout_seconds: float = 2.0


@dataclasses.dataclass(frozen=True)
class ServiceSpec:
    name: str
    port_envs: tuple[str, ...]
    command: tuple[str, ...]
    health: tuple[HealthSpec, ...]
    listener_ownership: str = "direct"
    environment: Mapping[str, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class DevConfig:
    services: tuple[ServiceSpec, ...]


@dataclasses.dataclass(frozen=True)
class ProcessRecord:
    service: str
    pid: int
    identity: str
    command_digest: str
    ports: tuple[int, ...]
    listener_ownership: str
    started_at: str
    delegated_container_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project": PROJECT_NAME,
            "service": self.service,
            "pid": self.pid,
            "identity": self.identity,
            "command_digest": self.command_digest,
            "ports": list(self.ports),
            "listener_ownership": self.listener_ownership,
            "started_at": self.started_at,
            "delegated_container_id": self.delegated_container_id,
        }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DevctlError(f"{label} must be a JSON object")
    return value


def _reject_unknown_keys(
    value: Mapping[str, Any], allowed: set[str], label: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DevctlError(f"{label} has unknown keys: {', '.join(unknown)}")


def _require_argv(value: Any, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise DevctlError(f"{label} must be a non-empty JSON argv array")
    if "\x00" in "".join(value):
        raise DevctlError(f"{label} contains a NUL byte")
    return tuple(value)


def _require_http_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("/"):
        raise DevctlError(f"{label} must be an absolute HTTP path")
    split = urllib.parse.urlsplit(value)
    if split.scheme or split.netloc or split.fragment:
        raise DevctlError(f"{label} must not contain a scheme, host, or fragment")
    return value


def _port_drift_details(parsed: Mapping[str, int]) -> str:
    missing = sorted(set(PORT_SPECS) - set(parsed))
    extra = sorted(set(parsed) - set(PORT_SPECS))
    changed = sorted(
        key for key in set(parsed) & set(PORT_SPECS) if parsed[key] != PORT_SPECS[key]
    )
    details: list[str] = []
    if missing:
        details.append(f"missing={missing}")
    if extra:
        details.append(f"extra={extra}")
    if changed:
        values = {key: (PORT_SPECS[key], parsed[key]) for key in changed}
        details.append("changed=" + repr(values))
    return "; ".join(details)


def parse_ports_env(path: Path) -> dict[str, int]:
    """Parse and strictly validate the repository's immutable port allocation."""

    if path.is_symlink() or not path.is_file():
        raise DevctlError(f"missing required port declaration: {path}")
    parsed: dict[str, int] = {}
    for line_number, original in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = original.split("#", 1)[0].strip()
        if not line:
            continue
        match = PORT_LINE_RE.fullmatch(line)
        if match is None:
            raise DevctlError(f"{path}:{line_number}: invalid ports.env declaration")
        key, raw_port = match.groups()
        if key in parsed:
            raise DevctlError(f"{path}:{line_number}: duplicate declaration for {key}")
        parsed[key] = int(raw_port)

    if parsed != PORT_SPECS:
        raise DevctlError(
            "ports.env does not match the exclusive allocation: "
            + _port_drift_details(parsed)
        )
    return parsed


def _semantic_expect(
    obj: Mapping[str, Any], label: str, service_name: str
) -> dict[str, Any]:
    expect = _require_object(obj.get("expect"), f"{label}.expect")
    if expect.get("service") != service_name or expect.get("status") != "ready":
        raise DevctlError(
            f"{label}.expect must include service={service_name!r} and status='ready'"
        )
    return expect


def _probe_timeout(obj: Mapping[str, Any], label: str) -> float:
    timeout = obj.get("timeout_seconds", 2.0)
    valid_number = isinstance(timeout, (int, float)) and not isinstance(timeout, bool)
    if not valid_number or not (
        MIN_PROBE_TIMEOUT_SECONDS <= timeout <= MAX_PROBE_TIMEOUT_SECONDS
    ):
        raise DevctlError(f"{label}.timeout_seconds must be between 0.05 and 10")
    return float(timeout)


def _http_status(obj: Mapping[str, Any], label: str) -> int:
    status = obj.get("expect_status")
    if not isinstance(status, int) or isinstance(status, bool):
        raise DevctlError(f"{label}.expect_status must be an explicit 2xx status")
    if not HTTP_SUCCESS_MIN <= status <= HTTP_SUCCESS_MAX:
        raise DevctlError(f"{label}.expect_status must be an explicit 2xx status")
    return status


def _parse_command_health(
    obj: Mapping[str, Any],
    label: str,
    service_name: str,
    port_env: str,
    timeout: float,
) -> HealthSpec:
    base_keys = {"port_env", "kind", "timeout_seconds"}
    _reject_unknown_keys(obj, base_keys | {"argv", "expect"}, label)
    return HealthSpec(
        port_env=port_env,
        kind="command-json",
        expect=_semantic_expect(obj, label, service_name),
        argv=_require_argv(obj.get("argv"), f"{label}.argv"),
        timeout_seconds=timeout,
    )


def _parse_http_health(
    obj: Mapping[str, Any],
    label: str,
    service_name: str,
    base: HealthSpec,
) -> HealthSpec:
    allowed = {"port_env", "kind", "timeout_seconds", "path", "expect_status"}
    path = _require_http_path(obj.get("path"), f"{label}.path")
    status = _http_status(obj, label)
    if base.kind == "http-json":
        _reject_unknown_keys(obj, allowed | {"expect"}, label)
        return HealthSpec(
            port_env=base.port_env,
            kind=base.kind,
            path=path,
            expect_status=status,
            expect=_semantic_expect(obj, label, service_name),
            timeout_seconds=base.timeout_seconds,
        )
    if base.kind == "http-text":
        _reject_unknown_keys(obj, allowed | {"expect_text"}, label)
        marker = obj.get("expect_text")
        if not isinstance(marker, str) or len(marker.strip()) < MIN_TEXT_MARKER_LENGTH:
            raise DevctlError(
                f"{label}.expect_text must be a stable marker of at least 8 characters"
            )
        return HealthSpec(
            port_env=base.port_env,
            kind=base.kind,
            path=path,
            expect_status=status,
            expect_text=marker,
            timeout_seconds=base.timeout_seconds,
        )
    _reject_unknown_keys(obj, allowed | {"expect_headers"}, label)
    if not any(token in path.lower() for token in ("ready", "health")):
        raise DevctlError(f"{label}.path must be a provider readiness/health endpoint")
    headers = _require_object(obj.get("expect_headers", {}), f"{label}.expect_headers")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in headers.items()
    ):
        raise DevctlError(f"{label}.expect_headers values must be strings")
    return HealthSpec(
        port_env=base.port_env,
        kind=base.kind,
        path=path,
        expect_status=status,
        expect_headers={key.lower(): value for key, value in headers.items()},
        timeout_seconds=base.timeout_seconds,
    )


def _parse_health(
    raw: Any, service_name: str, service_ports: set[str], index: int
) -> HealthSpec:
    label = f"service {service_name!r} health[{index}]"
    obj = _require_object(raw, label)
    port_env = obj.get("port_env")
    if not isinstance(port_env, str) or port_env not in service_ports:
        raise DevctlError(f"{label}.port_env must name one of the service's ports")
    kind = obj.get("kind")
    supported = {"http-json", "http-text", "http-ready", "command-json"}
    if not isinstance(kind, str) or kind not in supported:
        raise DevctlError(f"{label}.kind is not a supported semantic readiness probe")
    timeout = _probe_timeout(obj, label)
    if kind == "command-json":
        return _parse_command_health(obj, label, service_name, port_env, timeout)
    base = HealthSpec(port_env=port_env, kind=kind, timeout_seconds=timeout)
    return _parse_http_health(obj, label, service_name, base)


def _parse_port_envs(
    service: Mapping[str, Any], label: str, covered_ports: set[str]
) -> tuple[str, ...]:
    raw = service.get("port_envs")
    if (
        not isinstance(raw, list)
        or not raw
        or not all(isinstance(item, str) for item in raw)
    ):
        raise DevctlError(f"{label}.port_envs must be a non-empty string array")
    port_envs = tuple(raw)
    if len(set(port_envs)) != len(port_envs):
        raise DevctlError(f"{label}.port_envs contains a duplicate")
    unknown = sorted(set(port_envs) - set(PORT_SPECS))
    if unknown:
        raise DevctlError(
            f"{label}.port_envs leaves the exclusive allocation: {unknown}"
        )
    duplicate = sorted(set(port_envs) & covered_ports)
    if duplicate:
        raise DevctlError(
            f"{label}.port_envs already owned by another service: {duplicate}"
        )
    covered_ports.update(port_envs)
    return port_envs


def _parse_service_env(service: Mapping[str, Any], label: str) -> dict[str, str]:
    environment = _require_object(service.get("env", {}), f"{label}.env")
    if not all(isinstance(value, str) for value in environment.values()):
        raise DevctlError(f"{label}.env values must all be strings")
    protected = sorted(set(environment) & PROTECTED_ENV)
    if protected:
        raise DevctlError(
            f"{label}.env may not override protected variables: {protected}"
        )
    unsupported = sorted(set(environment) - SERVICE_ENV_ALLOWLIST)
    if unsupported:
        raise DevctlError(f"{label}.env contains unsupported variables: {unsupported}")
    return environment


def _parse_service(
    raw: Any,
    label: str,
    names: set[str],
    covered_ports: set[str],
) -> ServiceSpec:
    service = _require_object(raw, label)
    allowed = {"name", "port_envs", "command", "health", "listener_ownership", "env"}
    _reject_unknown_keys(service, allowed, label)
    name = service.get("name")
    if not isinstance(name, str) or SERVICE_NAME_RE.fullmatch(name) is None:
        raise DevctlError(f"{label}.name must match {SERVICE_NAME_RE.pattern}")
    if name in names:
        raise DevctlError(f"{label}: duplicate service name {name!r}")
    names.add(name)
    port_envs = _parse_port_envs(service, label, covered_ports)
    ownership = service.get("listener_ownership", "direct")
    if ownership not in {"direct", "delegated"}:
        raise DevctlError(f"{label}.listener_ownership must be 'direct' or 'delegated'")
    raw_health = service.get("health")
    if not isinstance(raw_health, list) or not raw_health:
        raise DevctlError(f"{label}.health must be a non-empty array")
    health = tuple(
        _parse_health(item, name, set(port_envs), index)
        for index, item in enumerate(raw_health)
    )
    if sorted(item.port_env for item in health) != sorted(port_envs):
        raise DevctlError(
            f"{label}.health must contain exactly one semantic readiness probe per port"
        )
    return ServiceSpec(
        name=name,
        port_envs=port_envs,
        command=_require_argv(service.get("command"), f"{label}.command"),
        health=health,
        listener_ownership=ownership,
        environment=_parse_service_env(service, label),
    )


def load_config(path: Path) -> DevConfig:
    """Load a complete, strict service/process and semantic-health contract."""

    if not path.is_file():
        raise DevctlError(
            f"missing service configuration {path}; refusing to fabricate "
            "product services"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DevctlError(f"cannot read service configuration {path}: {exc}") from exc
    obj = _require_object(raw, str(path))
    _reject_unknown_keys(obj, {"version", "services"}, str(path))
    if obj.get("version") != 1:
        raise DevctlError(f"{path}: version must be exactly 1")
    raw_services = obj.get("services")
    if not isinstance(raw_services, list) or not raw_services:
        raise DevctlError(f"{path}: services must be a non-empty array")
    names: set[str] = set()
    covered_ports: set[str] = set()
    services = tuple(
        _parse_service(item, f"{path}: services[{index}]", names, covered_ports)
        for index, item in enumerate(raw_services)
    )
    if covered_ports != set(PORT_SPECS):
        missing = sorted(set(PORT_SPECS) - covered_ports)
        raise DevctlError(f"{path}: services do not cover allocated ports: {missing}")
    return DevConfig(services)


class _ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _procfs_identity(pid: int) -> str | None:
    proc_dir = Path("/proc") / str(pid)
    try:
        stat_text = (proc_dir / "stat").read_text(encoding="utf-8")
    except FileNotFoundError, ProcessLookupError, PermissionError, OSError:
        return None
    close_paren = stat_text.rfind(")")
    fields = stat_text[close_paren + 2 :].split()
    if close_paren < 0 or len(fields) <= LINUX_START_TICKS_INDEX or fields[0] == "Z":
        return None
    return f"proc:{pid}:{fields[LINUX_START_TICKS_INDEX]}"


def _darwin_identity(pid: int) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        libproc.proc_pidinfo.restype = ctypes.c_int
        info = _ProcBsdInfo()
        size = ctypes.sizeof(info)
        result = libproc.proc_pidinfo(
            pid, DARWIN_PROC_PIDTBSDINFO, 0, ctypes.byref(info), size
        )
    except OSError, AttributeError:
        return None
    if result != size or info.pbi_pid != pid or info.pbi_status == DARWIN_ZOMBIE_STATUS:
        return None
    return f"darwin:{pid}:{info.pbi_start_tvsec}:{info.pbi_start_tvusec}"


def _ps_identity(pid: int) -> str | None:
    try:
        completed = subprocess.run(  # noqa: S603 -- fixed ps binary; pid is an int
            [
                "/bin/ps",
                "-p",
                str(pid),
                "-o",
                "stat=",
                "-o",
                "lstart=",
                "-o",
                "comm=",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    output = completed.stdout.strip()
    parts = output.split()
    if completed.returncode != 0 or not parts or parts[0].startswith("Z"):
        return None
    stable = " ".join(parts[1:])
    return "ps:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


def process_identity(pid: int) -> str | None:
    """Return a PID-reuse-resistant identity, or ``None`` if not running."""

    if pid <= 1:
        return None
    system = platform.system()
    if system == "Linux":
        return _procfs_identity(pid)
    if system == "Darwin":
        return _darwin_identity(pid)
    return _ps_identity(pid)


def parse_lsof_machine_output(raw: str, port: int) -> list[Listener]:
    """Parse ``lsof -Fpcn`` output without depending on column widths."""

    current_pid: int | None = None
    current_command = "unknown"
    listeners: list[Listener] = []
    for line in raw.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            try:
                current_pid = int(value)
            except ValueError:
                current_pid = None
            current_command = "unknown"
        elif field == "c" and current_pid is not None:
            current_command = value or "unknown"
        elif field == "n" and current_pid is not None:
            listeners.append(Listener(port, current_pid, current_command, value))
    unique: dict[tuple[int, str], Listener] = {
        (listener.pid, listener.endpoint): listener for listener in listeners
    }
    return list(unique.values())


def parse_lsof_block_output(raw: str) -> dict[int, list[Listener]]:
    """Parse one range query into the repository's ten-port inventory."""

    current_pid: int | None = None
    current_command = "unknown"
    listeners: dict[int, list[Listener]] = {port: [] for port in PORT_BLOCK}
    seen: set[tuple[int, int, str]] = set()
    for line in raw.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            try:
                current_pid = int(value)
            except ValueError:
                current_pid = None
            current_command = "unknown"
        elif field == "c" and current_pid is not None:
            current_command = value or "unknown"
        elif field == "n" and current_pid is not None:
            match = re.search(r":([0-9]+)$", value)
            if match is None:
                continue
            port = int(match.group(1))
            key = (port, current_pid, value)
            if port in listeners and key not in seen:
                listeners[port].append(
                    Listener(port, current_pid, current_command, value)
                )
                seen.add(key)
    return listeners


def _parse_compose_labels(raw: Any, label: str) -> dict[str, str]:
    if isinstance(raw, dict):
        if not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in raw.items()
        ):
            raise DevctlError(f"{label} has invalid Docker labels")
        return dict(raw)
    if not isinstance(raw, str):
        raise DevctlError(f"{label} has invalid Docker labels")
    labels: dict[str, str] = {}
    for entry in raw.split(","):
        if "=" not in entry:
            raise DevctlError(f"{label} has malformed Docker labels")
        key, value = entry.split("=", 1)
        if not key or key in labels:
            raise DevctlError(f"{label} has duplicate/empty Docker labels")
        labels[key] = value
    return labels


def _parse_compose_publisher(raw: Any, label: str) -> tuple[str, int, int, str]:
    value = _require_object(raw, label)
    address = value.get("URL")
    published_port = value.get("PublishedPort")
    target_port = value.get("TargetPort")
    protocol = value.get("Protocol")
    if (
        not isinstance(address, str)
        or not isinstance(published_port, int)
        or isinstance(published_port, bool)
        or not isinstance(target_port, int)
        or isinstance(target_port, bool)
        or not isinstance(protocol, str)
    ):
        raise DevctlError("Docker Compose returned an invalid published-port record")
    return address, published_port, target_port, protocol


def parse_compose_ps_publishers(raw: str) -> dict[str, ComposeServiceRecord]:
    """Parse exact scoped Compose state and host-to-container publishers."""

    if len(raw.encode("utf-8")) > MAX_COMPOSE_PS_BYTES:
        raise DevctlError("scoped Docker Compose inventory exceeded 256 KiB")
    by_service: dict[str, ComposeServiceRecord] = {}
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DevctlError(
                f"scoped Docker Compose inventory line {line_number} is not JSON"
            ) from exc
        item = _require_object(payload, f"Compose inventory line {line_number}")
        project = item.get("Project")
        service = item.get("Service")
        state = item.get("State")
        name = item.get("Name")
        container_id = item.get("ID")
        publishers = item.get("Publishers")
        if project != PROJECT_NAME:
            raise DevctlError(
                f"Docker Compose returned a foreign project at line {line_number}"
            )
        if (
            not isinstance(service, str)
            or SERVICE_NAME_RE.fullmatch(service) is None
            or not isinstance(state, str)
            or not isinstance(name, str)
            or not name
            or not isinstance(container_id, str)
            or CONTAINER_ID_RE.fullmatch(container_id) is None
            or not isinstance(publishers, list)
        ):
            raise DevctlError(
                f"Docker Compose returned an invalid service record at line "
                f"{line_number}"
            )
        if service in by_service:
            raise DevctlError(
                f"Docker Compose returned duplicate records for service {service!r}"
            )
        service_ports: set[tuple[str, int, int, str]] = set()
        for publisher_number, publisher in enumerate(publishers, 1):
            publisher_tuple = _parse_compose_publisher(
                publisher,
                f"Compose inventory line {line_number} publisher {publisher_number}",
            )
            if publisher_tuple in service_ports:
                raise DevctlError(
                    "Docker Compose returned a duplicate published-port record"
                )
            service_ports.add(publisher_tuple)
        by_service[service] = ComposeServiceRecord(
            container_id=container_id,
            state=state,
            name=name,
            publishers=frozenset(service_ports),
            labels=_parse_compose_labels(
                item.get("Labels"), f"Compose inventory line {line_number}"
            ),
        )
    return by_service


def parse_compose_config_hashes(raw: str) -> dict[str, str]:
    if len(raw.encode("utf-8")) > MAX_HEALTH_BODY_BYTES:
        raise DevctlError("scoped Docker Compose config hashes exceeded 64 KiB")
    hashes: dict[str, str] = {}
    for line_number, line in enumerate(raw.splitlines(), 1):
        parts = line.split()
        if (
            len(parts) != COMPOSE_HASH_FIELD_COUNT
            or SERVICE_NAME_RE.fullmatch(parts[0]) is None
            or COMPOSE_CONFIG_HASH_RE.fullmatch(parts[1]) is None
        ):
            raise DevctlError(
                f"invalid Docker Compose config hash at line {line_number}"
            )
        service, config_hash = parts
        if service in hashes:
            raise DevctlError(
                f"duplicate Docker Compose config hash for service {service!r}"
            )
        hashes[service] = config_hash
    return hashes


def resolve_compose_executable(docker: str, environment: Mapping[str, str]) -> Path:
    resolved_docker = Path(docker).resolve()
    home = Path(environment.get("HOME", ""))
    candidates = (
        resolved_docker.parent.parent / "cli-plugins" / "docker-compose",
        resolved_docker.parent.parent
        / "libexec"
        / "docker"
        / "cli-plugins"
        / "docker-compose",
        Path("/usr/local/lib/docker/cli-plugins/docker-compose"),
        Path("/usr/local/libexec/docker/cli-plugins/docker-compose"),
        Path("/usr/lib/docker/cli-plugins/docker-compose"),
        Path("/usr/libexec/docker/cli-plugins/docker-compose"),
        home / ".docker" / "cli-plugins" / "docker-compose",
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise DevctlError(
        "cannot resolve the Docker Compose plugin executable for scoped ownership"
    )


class DevController:
    """Strict lifecycle manager for this repository's exclusive block."""

    def __init__(
        self,
        root: Path,
        *,
        config_path: Path | None = None,
        environ: Mapping[str, str] | None = None,
        emit: Callable[[str], None] = print,
        verify_repository: bool = True,
    ) -> None:
        self.root = root.resolve()
        if verify_repository and self.root != REPOSITORY_ROOT:
            raise DevctlError(
                "repository lifecycle root must be this exact source checkout"
            )
        self.state_dir = self.root / ".dev"
        self.pids_dir = self.state_dir / "pids"
        self.logs_dir = self.state_dir / "logs"
        self.tmp_dir = self.state_dir / "tmp"
        self.cache_dir = self.state_dir / "cache"
        self.profile_dir = self.state_dir / "pw-profile"
        self.config_dir = self.state_dir / "config"
        self.data_dir = self.state_dir / "data"
        self.tool_state_dir = self.state_dir / "state"
        self.home_dir = self.state_dir / "home"
        self.environ = dict(os.environ if environ is None else environ)
        unknown_devctl = sorted(
            key
            for key in self.environ
            if key.startswith("DEVCTL_") and key not in DEVCTL_TUNING_ENV
        )
        if verify_repository and unknown_devctl:
            raise DevctlError(
                "unsupported lifecycle environment variables: " + repr(unknown_devctl)
            )
        if verify_repository and config_path is not None:
            raise DevctlError("repository lifecycle config cannot be overridden")
        configured = config_path or Path(
            self.environ.get("DEVCTL_CONFIG", "dev-services.json")
        )
        self.config_path = (
            configured if configured.is_absolute() else self.root / configured
        )
        self.emit = emit
        self.verify_repository = verify_repository
        canonical_config = self.root / "dev-services.json"
        if self.verify_repository and self.config_path != canonical_config:
            raise DevctlError(
                "repository lifecycle config must be the canonical dev-services.json"
            )
        # Retain child handles during an in-process up/down cycle so tests and
        # embedded callers can reap them cleanly.  Separate CLI invocations
        # rely on the durable identity record instead.
        self._children: dict[int, subprocess.Popen[bytes]] = {}
        self._verified_compose_path: Path | None = None

    @staticmethod
    def _ensure_private_directory(directory: Path) -> None:
        try:
            directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
        except FileExistsError:
            pass
        except OSError as exc:
            raise DevctlError(
                f"cannot create development state directory {directory}: {exc}"
            ) from exc
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(directory, flags)
        except OSError as exc:
            raise DevctlError(
                f"development state path is not a real directory: {directory}"
            ) from exc
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise DevctlError(
                    f"development state path is not a directory: {directory}"
                )
            os.fchmod(descriptor, PRIVATE_DIRECTORY_MODE)
            mode = stat.S_IMODE(os.fstat(descriptor).st_mode)
            if mode != PRIVATE_DIRECTORY_MODE:
                raise DevctlError(
                    f"development state directory mode is {mode:04o}, expected 0700: "
                    f"{directory}"
                )
        except OSError as exc:
            raise DevctlError(
                f"cannot secure development state directory {directory}: {exc}"
            ) from exc
        finally:
            os.close(descriptor)

    def _ensure_layout(self) -> None:
        if self.verify_repository and self.root.name != PROJECT_NAME:
            raise DevctlError(
                f"refusing to operate outside {PROJECT_NAME}: "
                f"resolved root is {self.root}"
            )
        if not self.root.is_dir():
            raise DevctlError(f"repository root does not exist: {self.root}")
        for directory in (
            self.state_dir,
            self.pids_dir,
            self.logs_dir,
            self.tmp_dir,
            self.cache_dir,
            self.profile_dir,
            self.config_dir,
            self.data_dir,
            self.tool_state_dir,
            self.home_dir,
        ):
            self._ensure_private_directory(directory)
        if self.verify_repository:
            git = shutil.which("git")
            if git is None:
                raise DevctlError("git is required to verify .dev isolation")
            checked = subprocess.run(  # noqa: S603 -- resolved git executable
                [git, "-C", str(self.root), "check-ignore", "--quiet", ".dev/probe"],
                check=False,
                capture_output=True,
                env=self._isolated_base_environment(),
                timeout=5,
            )
            if checked.returncode != 0:
                raise DevctlError(
                    ".dev/ is not git-ignored; refusing to create runtime state"
                )
            canonical_inputs = (
                self.root / "dev-services.json",
                self.root / "ports.env",
                self.root / "compose.yaml",
            )
            for path in canonical_inputs:
                if path.is_symlink() or not path.is_file():
                    raise DevctlError(
                        f"lifecycle input must be a regular non-symlink file: {path}"
                    )
                if path.resolve(strict=True) != path:
                    raise DevctlError(f"lifecycle input escaped the repository: {path}")

    @contextlib.contextmanager
    def _lock(self) -> Iterator[None]:
        lock_path = self.state_dir / "devctl.lock"
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise DevctlError(
                f"cannot open real repository lifecycle lock: {lock_path}"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                os.close(descriptor)
                raise DevctlError("repository lifecycle lock must be a regular file")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            os.close(descriptor)
            raise DevctlError("cannot secure repository lifecycle lock") from exc
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _listeners_for_port(self, port: int) -> list[Listener]:
        raw = self._run_lsof(f"-iTCP:{port}", f"port {port}")
        return parse_lsof_machine_output(raw, port)

    def _run_lsof(self, selector: str, label: str) -> str:
        lsof = shutil.which("lsof")
        if lsof is None:
            raise DevctlError("lsof is required to identify port holders safely")
        try:
            completed = _bounded_process_output(
                [
                    lsof,
                    "-nP",
                    "-a",
                    selector,
                    "-sTCP:LISTEN",
                    "-Fpcn",
                ],
                ProcessCaptureSpec(
                    cwd=self.root,
                    environment=self._isolated_base_environment(),
                    output_directory=self.tmp_dir,
                    timeout_seconds=20,
                    stdout_limit=MAX_LSOF_OUTPUT_BYTES,
                    stderr_limit=MAX_TOOL_STDERR_BYTES,
                    label=f"lsof {label}",
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DevctlError(f"cannot inspect {label} with lsof: {exc}") from exc
        if completed.returncode not in (0, 1):
            detail = completed.stderr.strip() or f"exit {completed.returncode}"
            raise DevctlError(f"lsof failed for {label}: {detail}")
        return completed.stdout

    def _all_listeners(self) -> dict[int, list[Listener]]:
        raw = self._run_lsof("-iTCP:4170-4179", "exclusive block 4170-4179")
        return parse_lsof_block_output(raw)

    @staticmethod
    def _endpoint_is_loopback(listener: Listener) -> bool:
        return listener.endpoint == f"{BIND_HOST}:{listener.port}"

    def _record_path(self, service: str) -> Path:
        return self.pids_dir / f"{service}.json"

    @staticmethod
    def _decode_record(raw: Any, source: Path) -> ProcessRecord:
        obj = _require_object(raw, str(source))
        required = {
            "schema_version",
            "project",
            "service",
            "pid",
            "identity",
            "command_digest",
            "ports",
            "listener_ownership",
            "started_at",
            "delegated_container_id",
        }
        _reject_unknown_keys(obj, required, str(source))
        if (
            set(obj) != required
            or obj.get("schema_version") != 1
            or obj.get("project") != PROJECT_NAME
        ):
            raise DevctlError(f"invalid or foreign PID record: {source}")
        service = obj.get("service")
        pid = obj.get("pid")
        identity = obj.get("identity")
        digest = obj.get("command_digest")
        ports = obj.get("ports")
        ownership = obj.get("listener_ownership")
        started_at = obj.get("started_at")
        delegated_container_id = obj.get("delegated_container_id")
        if not isinstance(service, str) or SERVICE_NAME_RE.fullmatch(service) is None:
            raise DevctlError(f"invalid service in PID record: {source}")
        if source.stem != service:
            raise DevctlError(f"PID record filename/service mismatch: {source}")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            raise DevctlError(f"invalid PID in record: {source}")
        if not isinstance(identity, str) or not identity:
            raise DevctlError(f"invalid process identity in record: {source}")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise DevctlError(f"invalid command digest in record: {source}")
        if (
            not isinstance(ports, list)
            or not ports
            or not all(
                isinstance(port, int) and not isinstance(port, bool) for port in ports
            )
            or any(port not in ALLOCATED_PORTS for port in ports)
            or len(set(ports)) != len(ports)
        ):
            raise DevctlError(f"invalid ports in PID record: {source}")
        if ownership not in {"direct", "delegated"}:
            raise DevctlError(f"invalid listener ownership in PID record: {source}")
        delegated_container_id = _validated_delegated_container_id(
            ownership, delegated_container_id, source
        )
        if not isinstance(started_at, str) or not started_at:
            raise DevctlError(f"invalid start timestamp in PID record: {source}")
        return ProcessRecord(
            service=service,
            pid=pid,
            identity=identity,
            command_digest=digest,
            ports=tuple(ports),
            listener_ownership=ownership,
            started_at=started_at,
            delegated_container_id=delegated_container_id,
        )

    def _load_records(self) -> dict[str, ProcessRecord]:
        records: dict[str, ProcessRecord] = {}
        for path in sorted(self.pids_dir.glob("*.json")):
            if path.is_symlink():
                raise DevctlError(f"refusing symlinked PID record: {path}")
            try:
                encoded = _read_private_pid_record(path)
                raw = json.loads(encoded.decode("utf-8"))
            except DevctlError:
                raise
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise DevctlError(f"cannot read PID record {path}: {exc}") from exc
            record = self._decode_record(raw, path)
            if record.service in records:
                raise DevctlError(f"duplicate PID record for {record.service}")
            records[record.service] = record
        return records

    def _write_record(self, record: ProcessRecord) -> None:
        destination = self._record_path(record.service)
        temporary = destination.with_suffix(".json.tmp")
        data = json.dumps(record.to_json(), sort_keys=True, indent=2) + "\n"
        descriptor = _open_exclusive_private_file(
            temporary, f"PID record temporary for {record.service}"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            with contextlib.suppress(OSError):
                os.close(descriptor)
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
            raise
        temporary.replace(destination)

    @staticmethod
    def _record_is_live(record: ProcessRecord) -> bool:
        return process_identity(record.pid) == record.identity

    def _live_delegated_records(
        self, records: Mapping[str, ProcessRecord]
    ) -> tuple[ProcessRecord, ...]:
        return tuple(
            record
            for record in records.values()
            if record.listener_ownership == "delegated" and self._record_is_live(record)
        )

    @staticmethod
    def _require_supported_delegates(
        delegated: Sequence[ProcessRecord],
    ) -> None:
        unsupported = sorted(
            record.service
            for record in delegated
            if record.service not in DELEGATED_COMPOSE_SERVICES
        )
        if unsupported:
            raise DevctlError(
                "delegated listener ownership has no scoped Compose mapping: "
                + repr(unsupported)
            )

    def _run_scoped_compose(self, arguments: Sequence[str], label: str) -> str:
        docker = shutil.which("docker")
        if docker is None:
            raise DevctlError(
                "docker is required to verify delegated listener ownership"
            )
        compose_path = self.root / "compose.yaml"
        ports_path = self.root / "ports.env"
        for path in (compose_path, ports_path):
            if path.is_symlink() or not path.is_file():
                raise DevctlError(
                    f"delegated ownership input must be a regular non-symlink file: "
                    f"{path}"
                )
        environment = self._isolated_base_environment()
        compose = self._verified_compose_executable(docker, environment)
        argv = [
            str(compose),
            "--project-name",
            PROJECT_NAME,
            "--env-file",
            str(ports_path),
            "--file",
            str(compose_path),
            *arguments,
        ]
        try:
            completed = _bounded_process_output(
                argv,
                ProcessCaptureSpec(
                    cwd=self.root,
                    environment=environment,
                    output_directory=self.tmp_dir,
                    timeout_seconds=10,
                    stdout_limit=MAX_COMPOSE_PS_BYTES,
                    stderr_limit=MAX_TOOL_STDERR_BYTES,
                    label=f"Docker Compose {label}",
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DevctlError(
                f"cannot run scoped Docker Compose {label}: {exc}"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip()[:512] or f"exit {completed.returncode}"
            raise DevctlError(f"scoped Docker Compose {label} failed: {detail}")
        return completed.stdout

    def _verified_compose_executable(
        self, docker: str, environment: Mapping[str, str]
    ) -> Path:
        compose = resolve_compose_executable(docker, environment)
        if self._verified_compose_path == compose:
            return compose
        try:
            completed = _bounded_process_output(
                [str(compose), "version", "--short"],
                ProcessCaptureSpec(
                    cwd=self.root,
                    environment=environment,
                    output_directory=self.tmp_dir,
                    timeout_seconds=10,
                    stdout_limit=MAX_VERSION_OUTPUT_BYTES,
                    stderr_limit=MAX_VERSION_OUTPUT_BYTES,
                    label="Docker Compose version probe",
                ),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DevctlError(
                "cannot execute scoped Docker Compose version probe"
            ) from exc
        if completed.returncode != 0:
            raise DevctlError(
                "scoped Docker Compose version probe exited with status "
                f"{completed.returncode}"
            )
        match = re.fullmatch(
            r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?",
            completed.stdout.strip(),
        )
        if match is None:
            raise DevctlError("scoped Docker Compose returned a malformed version")
        version = tuple(int(part) for part in match.groups())
        if version < MINIMUM_COMPOSE_VERSION:
            raise DevctlError(
                "scoped Docker Compose must be >=2.24.0, observed "
                + completed.stdout.strip()
            )
        self._verified_compose_path = compose
        return compose

    def _compose_ps_output(self) -> str:
        return self._run_scoped_compose(
            ("ps", "--all", "--no-trunc", "--format", "{{json .}}"),
            "ownership check",
        )

    def _compose_config_hashes(self) -> dict[str, str]:
        output = self._run_scoped_compose(("config", "--hash", "*"), "config hash")
        return parse_compose_config_hashes(output)

    def _running_compose_records(self) -> dict[str, ComposeServiceRecord]:
        output = self._run_scoped_compose(
            ("ps", "--no-trunc", "--format", "{{json .}}"),
            "running-service inventory",
        )
        running = parse_compose_ps_publishers(output)
        expected_services = set(DELEGATED_RECORD_BY_COMPOSE)
        unexpected = sorted(set(running) - expected_services)
        if unexpected:
            raise DevctlError(
                f"scoped Docker Compose has unexpected running services: {unexpected}"
            )
        config_hashes = self._compose_config_hashes()
        if set(config_hashes) != expected_services:
            raise DevctlError(
                "scoped Docker Compose config-hash set is incomplete for recovery"
            )
        for compose_service, actual in running.items():
            record_service = DELEGATED_RECORD_BY_COMPOSE[compose_service]
            _expected_service, expected_publishers = DELEGATED_COMPOSE_SERVICES[
                record_service
            ]
            expected_ports = tuple(
                sorted(publisher[1] for publisher in expected_publishers)
            )
            self._verify_compose_service_record(
                (record_service, expected_ports),
                compose_service,
                expected_publishers,
                actual,
                config_hashes[compose_service],
            )
        return running

    def _reconcile_orphaned_delegates(
        self,
        config: DevConfig,
        ports: Mapping[str, int],
        records: dict[str, ProcessRecord],
    ) -> list[str]:
        configured_services = {
            service.name: service
            for service in config.services
            if service.listener_ownership == "delegated"
        }
        if not configured_services:
            return []
        if set(configured_services) != set(DELEGATED_COMPOSE_SERVICES):
            return [
                "delegated lifecycle config does not match the scoped Compose "
                "recovery contract"
            ]
        try:
            running = self._running_compose_records()
        except DevctlError as exc:
            return [str(exc)]
        errors: list[str] = []
        for compose_service in sorted(running):
            record_service = DELEGATED_RECORD_BY_COMPOSE[compose_service]
            record = records.get(record_service)
            if record is None:
                errors.append(
                    f"running delegated Compose service {compose_service} has no "
                    "devctl ownership record; refusing to stop it"
                )
                continue
            if self._record_is_live(record):
                continue
            service = configured_services[record_service]
            ownership_error = self._orphan_ownership_error(
                record, service, ports, running[compose_service]
            )
            if ownership_error is not None:
                errors.append(ownership_error)
                continue
            try:
                self._run_scoped_compose(
                    ("stop", "--timeout", "3", compose_service),
                    f"orphan stop for {compose_service}",
                )
            except DevctlError as exc:
                errors.append(str(exc))
                continue
            if record is not None:
                try:
                    self._record_path(record_service).unlink(missing_ok=True)
                except OSError as exc:
                    errors.append(
                        f"cannot remove reconciled PID record for "
                        f"{record_service}: {exc}"
                    )
                    continue
                records.pop(record_service)
            self.emit(
                f"RECONCILED service={record_service} compose={compose_service} "
                "reason=missing-or-dead-wrapper"
            )
        return errors

    def _orphan_ownership_error(
        self,
        record: ProcessRecord,
        service: ServiceSpec,
        ports: Mapping[str, int],
        actual: ComposeServiceRecord,
    ) -> str | None:
        compose_service = DELEGATED_COMPOSE_SERVICES[service.name][0]
        if not self._record_matches_service(record, service, ports):
            return (
                f"stale delegated PID record for {record.service} does not match "
                f"current lifecycle ownership; refusing to stop {compose_service}"
            )
        if record.delegated_container_id != actual.container_id:
            return (
                f"stale delegated PID record for {record.service} is not bound to "
                f"running container {compose_service}; refusing to stop it"
            )
        return None

    def _required_compose_labels(
        self, compose_service: str, config_hash: str
    ) -> dict[str, str]:
        return {
            "com.docker.compose.project": PROJECT_NAME,
            "com.docker.compose.service": compose_service,
            "com.docker.compose.project.config_files": str(self.root / "compose.yaml"),
            "com.docker.compose.project.environment_file": str(self.root / "ports.env"),
            "com.docker.compose.project.working_dir": str(self.root),
            "com.docker.compose.oneoff": "False",
            "com.docker.compose.container-number": "1",
            "com.docker.compose.config-hash": config_hash,
        }

    def _verify_compose_service_record(
        self,
        ownership: tuple[str, tuple[int, ...]],
        compose_service: str,
        expected_publishers: frozenset[tuple[str, int, int, str]],
        actual: ComposeServiceRecord,
        config_hash: str,
    ) -> None:
        record_service, record_ports = ownership
        if actual.state != "running" or actual.publishers != expected_publishers:
            raise DevctlError(
                f"scoped Docker Compose ownership mismatch for {record_service}: "
                f"state={actual.state!r} publishers={sorted(actual.publishers)!r}"
            )
        expected_name = f"{PROJECT_NAME}-{compose_service}-1"
        if actual.name != expected_name:
            raise DevctlError(
                f"scoped Docker Compose container name mismatch for {record_service}"
            )
        required_labels = self._required_compose_labels(compose_service, config_hash)
        mismatched_labels = sorted(
            key
            for key, value in required_labels.items()
            if actual.labels.get(key) != value
        )
        if mismatched_labels:
            raise DevctlError(
                f"scoped Docker Compose provenance mismatch for {record_service}: "
                f"labels={mismatched_labels!r}"
            )
        expected_record_ports = frozenset(
            publisher[1] for publisher in expected_publishers
        )
        if frozenset(record_ports) != expected_record_ports:
            raise DevctlError(
                f"delegated PID record ports do not match Compose contract for "
                f"{record_service}"
            )

    def _verify_delegated_publishers(
        self,
        delegated: Sequence[ProcessRecord],
        publishers: Mapping[str, ComposeServiceRecord],
        config_hashes: Mapping[str, str],
        *,
        require_bound_identity: bool = True,
    ) -> set[tuple[str, int]]:
        expected_compose_services = {
            DELEGATED_COMPOSE_SERVICES[record.service][0] for record in delegated
        }
        if set(publishers) != expected_compose_services:
            raise DevctlError(
                "scoped Docker Compose service set does not match live delegated "
                f"records: expected={sorted(expected_compose_services)!r} "
                f"actual={sorted(publishers)!r}"
            )
        if set(config_hashes) != expected_compose_services:
            raise DevctlError(
                "scoped Docker Compose config-hash set does not match live "
                f"delegated records: expected={sorted(expected_compose_services)!r} "
                f"actual={sorted(config_hashes)!r}"
            )
        verified: set[tuple[str, int]] = set()
        for record in delegated:
            compose_service, expected_publishers = DELEGATED_COMPOSE_SERVICES[
                record.service
            ]
            self._verify_compose_service_record(
                (record.service, record.ports),
                compose_service,
                expected_publishers,
                publishers[compose_service],
                config_hashes[compose_service],
            )
            if (
                require_bound_identity
                and record.delegated_container_id
                != publishers[compose_service].container_id
            ):
                raise DevctlError(
                    f"delegated container identity mismatch for {record.service}"
                )
            verified.update((record.service, port) for port in record.ports)
        return verified

    def _bind_delegated_containers(self, records: dict[str, ProcessRecord]) -> None:
        delegated = self._live_delegated_records(records)
        if not delegated:
            return
        self._require_supported_delegates(delegated)
        publishers = parse_compose_ps_publishers(self._compose_ps_output())
        config_hashes = self._compose_config_hashes()
        self._verify_delegated_publishers(
            delegated,
            publishers,
            config_hashes,
            require_bound_identity=False,
        )
        for record in delegated:
            compose_service = DELEGATED_COMPOSE_SERVICES[record.service][0]
            container_id = publishers[compose_service].container_id
            if (
                record.delegated_container_id is not None
                and record.delegated_container_id != container_id
            ):
                raise DevctlError(
                    f"delegated container identity changed for {record.service}"
                )
            if record.delegated_container_id is not None:
                continue
            bound = dataclasses.replace(record, delegated_container_id=container_id)
            self._write_record(bound)
            records[record.service] = bound

    def _delegated_compose_ports(
        self, records: Mapping[str, ProcessRecord]
    ) -> set[tuple[str, int]]:
        delegated = self._live_delegated_records(records)
        if not delegated:
            return set()
        self._require_supported_delegates(delegated)
        publishers = parse_compose_ps_publishers(self._compose_ps_output())
        config_hashes = self._compose_config_hashes()
        return self._verify_delegated_publishers(delegated, publishers, config_hashes)

    @staticmethod
    def _listener_owner(
        listener: Listener,
        records: Mapping[str, ProcessRecord],
        delegated_ports: Set[tuple[str, int]] = frozenset(),
    ) -> ProcessRecord | None:
        for record in records.values():
            if listener.port not in record.ports or not DevController._record_is_live(
                record
            ):
                continue
            direct_process_group = listener.pid == record.pid
            if record.listener_ownership == "direct":
                with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                    direct_process_group = (
                        direct_process_group or os.getpgid(listener.pid) == record.pid
                    )
            if record.listener_ownership == "delegated":
                if (record.service, listener.port) in delegated_ports:
                    return record
                continue
            if direct_process_group:
                return record
        return None

    def _inspect_listener(
        self,
        listener: Listener,
        records: Mapping[str, ProcessRecord],
        *,
        announce: bool,
        delegated_ports: Set[tuple[str, int]] = frozenset(),
    ) -> list[str]:
        owner = self._listener_owner(listener, records, delegated_ports)
        classification = (
            f"managed:{owner.service}:{owner.listener_ownership}"
            if owner
            else "FOREIGN"
        )
        if announce:
            self.emit(
                f"HELD port={listener.port} pid={listener.pid} "
                f"command={listener.command!r} address={listener.endpoint!r} "
                f"owner={classification}"
            )
        errors: list[str] = []
        if not self._endpoint_is_loopback(listener):
            errors.append(
                f"port {listener.port} is bound at {listener.endpoint!r}, "
                f"not {BIND_HOST}:{listener.port}"
            )
        if owner is None:
            errors.append(
                f"foreign holder on port {listener.port}: pid={listener.pid} "
                f"command={listener.command!r}"
            )
        return errors

    def _inspect_record_identity(
        self, record: ProcessRecord, *, announce: bool
    ) -> str | None:
        identity = process_identity(record.pid)
        if identity is None:
            if announce:
                self.emit(f"STALE service={record.service} pid={record.pid}")
            return None
        if identity == record.identity:
            return None
        return (
            f"PID reuse/ownership mismatch for {record.service}: "
            f"refusing pid {record.pid}"
        )

    def _inventory(
        self,
        records: Mapping[str, ProcessRecord],
        *,
        announce: bool,
    ) -> tuple[dict[int, list[Listener]], list[str]]:
        listeners = self._all_listeners()
        errors: list[str] = []
        delegated_ports: set[tuple[str, int]] = set()
        try:
            delegated_ports = self._delegated_compose_ports(records)
        except DevctlError as exc:
            errors.append(str(exc))
        for port in PORT_BLOCK:
            current = listeners[port]
            if not current:
                if announce:
                    self.emit(f"FREE port={port}")
                continue
            for listener in current:
                errors.extend(
                    self._inspect_listener(
                        listener,
                        records,
                        announce=announce,
                        delegated_ports=delegated_ports,
                    )
                )
        for record in records.values():
            error = self._inspect_record_identity(record, announce=announce)
            if error is not None:
                errors.append(error)
        return listeners, errors

    def _common_preflight(self) -> tuple[dict[str, int], dict[str, ProcessRecord]]:
        self._ensure_layout()
        ports = parse_ports_env(self.root / "ports.env")
        records = self._load_records()
        _, errors = self._inventory(records, announce=True)
        if errors:
            raise DevctlError(
                "preflight failed:\n- " + "\n- ".join(sorted(set(errors)))
            )
        return ports, records

    def preflight(self) -> None:
        self._ensure_layout()
        with self._lock():
            self._common_preflight()
        self.emit(
            f"PREFLIGHT OK project={PROJECT_NAME} host={BIND_HOST} "
            "ports=4170-4179 state=.dev"
        )

    def _isolated_base_environment(self) -> dict[str, str]:
        env = {key: self.environ[key] for key in CHILD_HOST_ENV if key in self.environ}
        env.setdefault("PATH", os.defpath)
        env.update(
            {
                "HOME": str(self.home_dir),
                "TMPDIR": str(self.tmp_dir),
                "XDG_CACHE_HOME": str(self.cache_dir),
                "XDG_CONFIG_HOME": str(self.config_dir),
                "XDG_DATA_HOME": str(self.data_dir),
                "XDG_STATE_HOME": str(self.tool_state_dir),
                "DOCKER_CONFIG": str(self.config_dir / "docker"),
                "UV_CACHE_DIR": str(self.cache_dir / "uv"),
                "PNPM_HOME": str(self.data_dir / "pnpm"),
                "npm_config_cache": str(self.cache_dir / "npm"),
                "PIP_CACHE_DIR": str(self.cache_dir / "pip"),
                "PYTHONPYCACHEPREFIX": str(self.cache_dir / "pycache"),
                "PLAYWRIGHT_USER_DATA_DIR": str(self.profile_dir),
            }
        )
        return env

    def _service_environment(
        self,
        service: ServiceSpec,
        ports: Mapping[str, int],
    ) -> dict[str, str]:
        env = self._isolated_base_environment()
        env.update({key: str(value) for key, value in ports.items()})
        env.update(
            {
                "HOST": BIND_HOST,
                "BIND_HOST": BIND_HOST,
                "DEVCTL_HOST": BIND_HOST,
                "PORT": str(ports[service.port_envs[0]]),
                "PORTS": ",".join(str(ports[key]) for key in service.port_envs),
                "COMPOSE_PROJECT_NAME": PROJECT_NAME,
                "DEVCTL_PROJECT": PROJECT_NAME,
                "DEVCTL_SERVICE": service.name,
                "DEVCTL_ROOT": str(self.root),
                "DEVCTL_STATE_DIR": str(self.state_dir),
                "POSTGRES_DB": "gatewaygs_ai_4_earth_hackathon",
                "POSTGRES_USER": "gatewaygs_ai_4_earth_hackathon",
                "DEVCTL_REDIS_DB": "7",
                "OBJECT_STORAGE_BUCKET": PROJECT_NAME,
            }
        )
        for key, raw_value in service.environment.items():
            env[key] = self._expand(raw_value, env, f"service {service.name} env {key}")
        return env

    @staticmethod
    def _expand(value: str, env: Mapping[str, str], label: str) -> str:
        try:
            return string.Template(value).substitute(env)
        except (KeyError, ValueError) as exc:
            raise DevctlError(
                f"{label} has an unresolved/invalid environment placeholder: {exc}"
            ) from exc

    def _runtime_argv(
        self, service: ServiceSpec, env: Mapping[str, str]
    ) -> tuple[str, ...]:
        return tuple(
            self._expand(argument, env, f"service {service.name} command")
            for argument in service.command
        )

    @staticmethod
    def _command_digest(
        argv: Sequence[str], env: Mapping[str, str], service: ServiceSpec
    ) -> str:
        # The child environment is an explicit non-secret allowlist. Hash its complete
        # expanded form so policy, PATH, cache boundary, and tuning drift cannot reuse
        # an older process. Only the digest, never the values, is persisted.
        material = {
            "argv": list(argv),
            "environment": dict(sorted(env.items())),
            "service": service.name,
            "ports": [env[key] for key in service.port_envs],
            "host": env["HOST"],
            "project": env["COMPOSE_PROJECT_NAME"],
            "ownership": service.listener_ownership,
        }
        encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    def _persist_started_record(self, record: ProcessRecord) -> None:
        try:
            self._write_record(record)
        except BaseException as persistence_error:
            cleanup_errors = self._rollback_started((record,))
            temporary = self._record_path(record.service).with_suffix(".json.tmp")
            try:
                temporary.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_errors.append(f"{record.service} temporary record: {exc}")
            if cleanup_errors:
                raise DevctlError(
                    "PID-record persistence failed and owned child cleanup also "
                    "failed:\n- " + "\n- ".join(cleanup_errors)
                ) from persistence_error
            if isinstance(persistence_error, (KeyboardInterrupt, SystemExit)):
                raise
            raise DevctlError(
                f"cannot persist PID ownership record for {record.service}"
            ) from persistence_error

    def _start_service(
        self,
        service: ServiceSpec,
        ports: Mapping[str, int],
    ) -> ProcessRecord:
        env = self._service_environment(service, ports)
        argv = self._runtime_argv(service, env)
        digest = self._command_digest(argv, env, service)
        log_path = self.logs_dir / f"{service.name}.log"
        descriptor = _open_private_service_log(log_path, service.name)
        try:
            with os.fdopen(descriptor, "ab", buffering=0) as log_handle:
                process = subprocess.Popen(  # noqa: S603 -- strict argv, shell disabled
                    list(argv),
                    cwd=self.root,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
                self._children[process.pid] = process
        except OSError as exc:
            with contextlib.suppress(OSError):
                os.close(descriptor)
            raise DevctlError(f"cannot start {service.name}: {exc}") from exc

        deadline = time.monotonic() + 1.0
        identity: str | None = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            identity = process_identity(process.pid)
            if identity is not None:
                break
            time.sleep(0.01)
        if identity is None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(process.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1)
            self._children.pop(process.pid, None)
            raise DevctlError(
                f"service {service.name} exited before a process identity could be "
                f"recorded; see {log_path}"
            )

        record = ProcessRecord(
            service=service.name,
            pid=process.pid,
            identity=identity,
            command_digest=digest,
            ports=tuple(ports[key] for key in service.port_envs),
            listener_ownership=service.listener_ownership,
            started_at=dt.datetime.now(dt.UTC).isoformat(),
        )
        self._persist_started_record(record)
        grace = self._duration_env("DEVCTL_STARTUP_GRACE_SECONDS", 0.15, 0.0, 5.0)
        if grace:
            time.sleep(grace)
        if process.poll() is not None or not self._record_is_live(record):
            if process.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(process.pid, signal.SIGTERM)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
            self._children.pop(process.pid, None)
            self._record_path(service.name).unlink(missing_ok=True)
            raise DevctlError(
                f"service {service.name} exited during startup; see {log_path}"
            )
        self.emit(
            f"STARTED service={service.name} pid={record.pid} "
            f"ports={','.join(map(str, record.ports))}"
        )
        return record

    def _duration_env(
        self, key: str, default: float, minimum: float, maximum: float
    ) -> float:
        raw = self.environ.get(key, str(default))
        try:
            value = float(raw)
        except ValueError as exc:
            raise DevctlError(f"{key} must be numeric") from exc
        if not minimum <= value <= maximum:
            raise DevctlError(f"{key} must be between {minimum} and {maximum}")
        return value

    @staticmethod
    def _require_identity(
        record: ProcessRecord, current: str | None, action: str
    ) -> None:
        if current != record.identity:
            raise DevctlError(
                f"PID ownership mismatch for {record.service}; refusing {action} "
                f"for pid {record.pid}"
            )

    @staticmethod
    def _wait_until_stopped(record: ProcessRecord, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = process_identity(record.pid)
            if current is None:
                return True
            DevController._require_identity(record, current, "another signal")
            time.sleep(0.05)
        return False

    def _finish_stop(
        self, record: ProcessRecord, *, remove_record: bool, already_exited: bool
    ) -> None:
        if remove_record:
            self._record_path(record.service).unlink(missing_ok=True)
        child = self._children.pop(record.pid, None)
        if child is not None:
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired as exc:
                self._children[record.pid] = child
                raise DevctlError(
                    f"owned child {record.pid} for {record.service} was not reaped"
                ) from exc
        suffix = " already-exited=true" if already_exited else ""
        self.emit(f"STOPPED service={record.service} pid={record.pid}{suffix}")

    def _terminate_record(self, record: ProcessRecord, *, remove_record: bool) -> None:
        current = process_identity(record.pid)
        if current is None:
            self._finish_stop(record, remove_record=remove_record, already_exited=True)
            return
        self._require_identity(record, current, "SIGTERM")
        os.kill(record.pid, signal.SIGTERM)
        timeout = self._duration_env("DEVCTL_SHUTDOWN_TIMEOUT_SECONDS", 5.0, 0.1, 60.0)
        if not self._wait_until_stopped(record, timeout):
            self._require_identity(record, process_identity(record.pid), "SIGKILL")
            os.kill(record.pid, signal.SIGKILL)
            if not self._wait_until_stopped(record, 2.0):
                raise DevctlError(
                    f"owned process {record.pid} for {record.service} did not stop"
                )
        self._finish_stop(record, remove_record=remove_record, already_exited=False)

    def _reconcile_existing(
        self,
        config: DevConfig,
        ports: Mapping[str, int],
        records: dict[str, ProcessRecord],
    ) -> None:
        expected_names = {service.name for service in config.services}
        unexpected = sorted(set(records) - expected_names)
        if unexpected:
            raise DevctlError(
                f"PID records are not present in current config: {unexpected}; "
                "run down safely first"
            )
        for service in config.services:
            record = records.get(service.name)
            if record is None:
                continue
            if not self._record_is_live(record):
                self._record_path(service.name).unlink(missing_ok=True)
                records.pop(service.name)
                continue
            config_matches = self._record_matches_service(record, service, ports)
            if not config_matches:
                raise DevctlError(
                    f"running service {service.name} does not match current config; "
                    "run down first"
                )
            self.emit(f"RUNNING service={service.name} pid={record.pid}")

    def _record_matches_service(
        self,
        record: ProcessRecord,
        service: ServiceSpec,
        ports: Mapping[str, int],
    ) -> bool:
        environment = self._service_environment(service, ports)
        argv = self._runtime_argv(service, environment)
        expected_ports = tuple(ports[key] for key in service.port_envs)
        return (
            record.command_digest == self._command_digest(argv, environment, service)
            and record.ports == expected_ports
            and record.listener_ownership == service.listener_ownership
            and (
                service.listener_ownership != "delegated"
                or record.delegated_container_id is not None
            )
        )

    def _start_missing(
        self,
        config: DevConfig,
        ports: Mapping[str, int],
        records: dict[str, ProcessRecord],
        started: list[ProcessRecord],
    ) -> None:
        for service in config.services:
            if service.name in records:
                continue
            record = self._start_service(service, ports)
            records[service.name] = record
            started.append(record)

    def _require_clean_inventory(self, records: Mapping[str, ProcessRecord]) -> None:
        _, errors = self._inventory(records, announce=True)
        if errors:
            raise DevctlError(
                "post-start ownership check failed:\n- " + "\n- ".join(errors)
            )

    def _rollback_started(self, records: Iterable[ProcessRecord]) -> list[str]:
        errors: list[str] = []
        for record in reversed(tuple(records)):
            try:
                self._terminate_record(record, remove_record=True)
            except (DevctlError, ProcessLookupError, PermissionError) as exc:
                errors.append(f"{record.service}: {exc}")
        return errors

    def up(self) -> None:
        self._ensure_layout()
        with self._lock():
            ports, records = self._common_preflight()
            config = load_config(self.config_path)
            self._reconcile_existing(config, ports, records)
            started: list[ProcessRecord] = []
            try:
                self._start_missing(config, ports, records, started)
                self._bind_delegated_containers(records)
                self._require_clean_inventory(records)
            except BaseException as startup_error:
                rollback_errors = self._rollback_started(started)
                if rollback_errors:
                    detail = "\n- ".join(rollback_errors)
                    raise DevctlError(
                        "startup failed and owned-service rollback also failed:\n- "
                        + detail
                    ) from startup_error
                raise
        self.emit("UP OK; run dev:health for semantic readiness")

    def _stop_and_release(self, record: ProcessRecord) -> list[str]:
        try:
            self._terminate_record(record, remove_record=False)
        except (DevctlError, ProcessLookupError, PermissionError) as exc:
            return [str(exc)]
        release_timeout = self._duration_env(
            "DEVCTL_SHUTDOWN_TIMEOUT_SECONDS", 5.0, 0.1, 60.0
        )
        release_deadline = time.monotonic() + release_timeout
        held: list[Listener] = []
        while time.monotonic() < release_deadline:
            block_listeners = self._all_listeners()
            held = [
                listener for port in record.ports for listener in block_listeners[port]
            ]
            if not held:
                self._record_path(record.service).unlink(missing_ok=True)
                return []
            time.sleep(0.05)
        detail = ", ".join(f"{item.port}/pid={item.pid}" for item in held)
        return [f"listeners remained after stopping {record.service}: {detail}"]

    @staticmethod
    def _remaining_listener_errors(
        listeners: Mapping[int, list[Listener]],
    ) -> list[str]:
        return [
            f"port {port} remains held by pid={listener.pid} "
            f"command={listener.command!r}; not killed"
            for port, current in listeners.items()
            for listener in current
        ]

    def down(self) -> None:
        self._ensure_layout()
        errors: list[str] = []
        with self._lock():
            ports = parse_ports_env(self.root / "ports.env")
            records = self._load_records()
            if self.verify_repository or self.config_path.is_file():
                config = load_config(self.config_path)
                errors.extend(
                    self._reconcile_orphaned_delegates(config, ports, records)
                )
            _, inventory_errors = self._inventory(records, announce=True)
            # Foreign holders are reported before any signal.  They do not become
            # signal targets and do not prevent safely stopping an independent,
            # identity-verified owned PID.
            errors.extend(inventory_errors)
            if not records:
                if errors:
                    raise DevctlError(
                        "down left foreign/unsafe holders:\n- " + "\n- ".join(errors)
                    )
                self.emit("DOWN OK; no owned services were recorded")
                return
            for record in records.values():
                errors.extend(self._stop_and_release(record))
            errors.extend(self._remaining_listener_errors(self._all_listeners()))
        if errors:
            raise DevctlError(
                "down completed with safe refusals:\n- "
                + "\n- ".join(sorted(set(errors)))
            )
        self.emit("DOWN OK; all recorded services stopped and all block ports are free")

    @staticmethod
    def _json_contains(actual: Any, expected: Any) -> bool:
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(
                key in actual and DevController._json_contains(actual[key], value)
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            return isinstance(actual, list) and actual == expected
        return bool(actual == expected)

    def _http_get(self, url: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect()
        )
        request = urllib.request.Request(  # noqa: S310 -- URL is fixed http loopback
            url,
            headers={"Accept": "application/json, text/plain, text/html"},
            method="GET",
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(MAX_HEALTH_BODY_BYTES + 1)
                if len(body) > MAX_HEALTH_BODY_BYTES:
                    raise DevctlError("readiness response exceeded 64 KiB")
                return (
                    int(response.status),
                    {key.lower(): value for key, value in response.headers.items()},
                    body,
                )
        except urllib.error.HTTPError as exc:
            return (
                int(exc.code),
                {key.lower(): value for key, value in exc.headers.items()},
                b"",
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DevctlError(f"HTTP readiness request failed: {exc}") from exc

    def _probe_command_json(
        self,
        service: ServiceSpec,
        health: HealthSpec,
        ports: Mapping[str, int],
    ) -> None:
        port = ports[health.port_env]
        env = self._service_environment(service, ports)
        argv = [
            self._expand(argument, env, f"service {service.name} health command")
            for argument in health.argv
        ]
        try:
            completed = subprocess.run(  # noqa: S603 -- validated argv, shell disabled
                argv,
                cwd=self.root,
                env=env,
                check=False,
                capture_output=True,
                timeout=health.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DevctlError(
                f"{service.name}:{port} readiness command failed: {exc}"
            ) from exc
        if completed.returncode != 0:
            raise DevctlError(
                f"{service.name}:{port} readiness command exited {completed.returncode}"
            )
        if len(completed.stdout) > MAX_HEALTH_BODY_BYTES:
            raise DevctlError(f"{service.name}:{port} readiness output exceeded 64 KiB")
        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DevctlError(
                f"{service.name}:{port} readiness output is not JSON"
            ) from exc
        if not self._json_contains(payload, health.expect):
            raise DevctlError(
                f"{service.name}:{port} semantic readiness JSON did not match"
            )

    @staticmethod
    def _require_http_health(health: HealthSpec) -> tuple[str, int]:
        if health.path is None or health.expect_status is None:
            raise DevctlError("invalid internal HTTP readiness contract")
        return health.path, health.expect_status

    def _probe_http(
        self,
        service: ServiceSpec,
        health: HealthSpec,
        ports: Mapping[str, int],
    ) -> None:
        port = ports[health.port_env]
        path, expected_status = self._require_http_health(health)
        url = f"http://{BIND_HOST}:{port}{path}"
        status, headers, body = self._http_get(url, health.timeout_seconds)
        if status != expected_status:
            raise DevctlError(
                f"{service.name}:{port} readiness returned HTTP {status}, "
                f"expected {expected_status}"
            )
        if health.kind == "http-ready":
            self._probe_ready_headers(service, port, health, headers)
            return
        if health.kind == "http-text":
            self._probe_text_body(service, port, health, body)
            return
        self._probe_json_body(service, port, health, headers, body)

    @staticmethod
    def _probe_ready_headers(
        service: ServiceSpec,
        port: int,
        health: HealthSpec,
        headers: Mapping[str, str],
    ) -> None:
        for key, expected in (health.expect_headers or {}).items():
            if headers.get(key) != expected:
                raise DevctlError(
                    f"{service.name}:{port} readiness header {key!r} did not match"
                )

    @staticmethod
    def _probe_text_body(
        service: ServiceSpec, port: int, health: HealthSpec, body: bytes
    ) -> None:
        try:
            text_body = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DevctlError(
                f"{service.name}:{port} readiness body is not UTF-8"
            ) from exc
        if health.expect_text is None or health.expect_text not in text_body:
            raise DevctlError(f"{service.name}:{port} readiness marker was absent")

    @staticmethod
    def _probe_json_body(
        service: ServiceSpec,
        port: int,
        health: HealthSpec,
        headers: Mapping[str, str],
        body: bytes,
    ) -> None:
        content_type = headers.get("content-type", "").lower()
        if "application/json" not in content_type:
            raise DevctlError(
                f"{service.name}:{port} readiness response is not application/json"
            )
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DevctlError(
                f"{service.name}:{port} readiness body is not valid JSON"
            ) from exc
        if not DevController._json_contains(payload, health.expect):
            raise DevctlError(
                f"{service.name}:{port} semantic readiness JSON did not match"
            )

    def _probe(
        self,
        service: ServiceSpec,
        health: HealthSpec,
        ports: Mapping[str, int],
    ) -> None:
        if health.kind == "command-json":
            self._probe_command_json(service, health, ports)
            return
        self._probe_http(service, health, ports)

    def _validate_health_records(
        self,
        config: DevConfig,
        ports: Mapping[str, int],
        records: Mapping[str, ProcessRecord],
    ) -> None:
        expected_names = {service.name for service in config.services}
        if set(records) != expected_names:
            missing = sorted(expected_names - set(records))
            extra = sorted(set(records) - expected_names)
            raise DevctlError(
                "semantic health requires exact PID ownership records; "
                f"missing={missing} extra={extra}"
            )
        for service in config.services:
            record = records[service.name]
            if not self._record_is_live(record):
                raise DevctlError(f"service {service.name} process is not owned/alive")
            env = self._service_environment(service, ports)
            argv = self._runtime_argv(service, env)
            if record.command_digest != self._command_digest(argv, env, service):
                raise DevctlError(
                    f"service {service.name} runtime differs from current config"
                )

    def _endpoint_pending_reason(
        self,
        service: ServiceSpec,
        health: HealthSpec,
        records: Mapping[str, ProcessRecord],
        listeners: Mapping[int, list[Listener]],
        *,
        delegated_ports: Set[tuple[str, int]] = frozenset(),
    ) -> str | None:
        port = PORT_SPECS[health.port_env]
        current = listeners[port]
        if not current:
            return "no listening socket yet"
        record = records[service.name]
        invalid = [
            listener
            for listener in current
            if not self._endpoint_is_loopback(listener)
            or self._listener_owner(listener, records, delegated_ports) != record
        ]
        if invalid:
            details = ", ".join(
                f"pid={item.pid} address={item.endpoint}" for item in invalid
            )
            raise DevctlError(
                f"unsafe/foreign listener for {service.name}:{port}: {details}"
            )
        try:
            self._probe(service, health, PORT_SPECS)
        except DevctlError as exc:
            return str(exc)
        return None

    def _health_pass(
        self,
        config: DevConfig,
        ports: Mapping[str, int],
        records: Mapping[str, ProcessRecord],
    ) -> dict[str, str]:
        for service in config.services:
            if not self._record_is_live(records[service.name]):
                raise DevctlError(
                    f"service {service.name} exited while waiting for readiness"
                )
        listeners = self._all_listeners()
        delegated_ports = self._delegated_compose_ports(records)
        pending: dict[str, str] = {}
        for service in config.services:
            for health in service.health:
                port = ports[health.port_env]
                reason = self._endpoint_pending_reason(
                    service,
                    health,
                    records,
                    listeners,
                    delegated_ports=delegated_ports,
                )
                if reason is not None:
                    pending[f"{service.name}:{port}"] = reason
        return pending

    def _emit_ready(self, config: DevConfig, ports: Mapping[str, int]) -> None:
        for service in config.services:
            for health in service.health:
                self.emit(
                    f"READY service={service.name} port={ports[health.port_env]} "
                    f"probe={health.kind}"
                )
        self.emit("HEALTH OK; all allocated ports passed semantic readiness")

    def health(self) -> None:
        self._ensure_layout()
        with self._lock():
            ports = parse_ports_env(self.root / "ports.env")
            config = load_config(self.config_path)
            records = self._load_records()
            self._validate_health_records(config, ports, records)
            timeout = self._duration_env(
                "DEVCTL_HEALTH_TIMEOUT_SECONDS", 30.0, 0.05, 600.0
            )
            interval = self._duration_env(
                "DEVCTL_HEALTH_INTERVAL_SECONDS", 0.25, 0.01, 5.0
            )
            deadline = time.monotonic() + timeout
            while True:
                pending = self._health_pass(config, ports, records)
                if not pending:
                    self._emit_ready(config, ports)
                    return
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
            detail = "\n- ".join(
                f"{key}: {value}" for key, value in sorted(pending.items())
            )
            raise DevctlError(
                f"semantic readiness timed out after {timeout:g}s:\n- {detail}"
            )


def _default_root() -> Path:
    return REPOSITORY_ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("preflight", "up", "down", "health"),
        help="lifecycle action",
    )
    parser.add_argument(
        "--root", type=Path, default=_default_root(), help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--config", type=Path, help="service config (default: dev-services.json)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        controller = DevController(args.root, config_path=args.config)
        getattr(controller, args.command)()
    except DevctlError as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("ERROR: interrupted\n")
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
