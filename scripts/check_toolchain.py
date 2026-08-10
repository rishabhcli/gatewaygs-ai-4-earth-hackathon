#!/usr/bin/env python3
"""Fail closed when the repository toolchain or its pins drift."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


EXPECTED_VERSIONS: Mapping[str, str] = {
    "python": "3.14.7",
    "node": "24.19.0",
    "uv": "0.12.3",
    "pnpm": "11.21.0",
}
VERSION_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "python": re.compile(r"^Python (?P<version>\d+\.\d+\.\d+)$"),
    "node": re.compile(r"^v(?P<version>\d+\.\d+\.\d+)$"),
    "uv": re.compile(r"^uv (?P<version>\d+\.\d+\.\d+)(?:\s.*)?$"),
    "pnpm": re.compile(r"^(?P<version>\d+\.\d+\.\d+)$"),
}
PROBE_FLAGS: Mapping[str, str] = {
    "python": "--version",
    "node": "--version",
    "uv": "--version",
    "pnpm": "--version",
}
PROBE_TIMEOUT_SECONDS = 15.0
PNPM_PROBE_TIMEOUT_SECONDS = 60.0
DOCKER_ENGINE_VERSION_FIELDS = 2
MINIMUM_DOCKER_VERSION = (24, 0, 0)
MINIMUM_COMPOSE_VERSION = (2, 24, 0)
NUMERIC_VERSION_PATTERN = re.compile(
    r"^v?(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)(?:[-+].*)?$"
)


class ToolchainError(RuntimeError):
    """A deterministic, user-safe toolchain validation failure."""


@dataclass(frozen=True)
class ToolProbe:
    name: str
    executable: Path
    version: str


def parse_version_output(name: str, output: str) -> str:
    """Return a normalized version from one supported tool's output."""

    pattern = VERSION_PATTERNS.get(name)
    if pattern is None:
        raise ToolchainError(f"unsupported tool probe: {name}")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ToolchainError(f"{name} version output must contain exactly one line")
    match = pattern.fullmatch(lines[0])
    if match is None:
        raise ToolchainError(f"{name} returned malformed version output")
    return match.group("version")


def resolve_executable(value: str | None, name: str) -> Path:
    """Resolve an explicit path or a PATH lookup to a regular executable."""

    candidate = value or shutil.which(name)
    if not candidate:
        raise ToolchainError(f"required tool is unavailable: {name}")
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        resolved = shutil.which(str(path))
        if resolved is None:
            raise ToolchainError(f"required tool is unavailable: {name}")
        path = Path(resolved)
    path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ToolchainError(f"required tool is not executable: {name}")
    return path


def probe_tool(
    name: str,
    executable: str | None,
    *,
    node_executable: Path | None = None,
) -> ToolProbe:
    """Execute a bounded, argv-only version probe."""

    path = resolve_executable(executable, name)
    environment = dict(os.environ)
    if name == "pnpm" and node_executable is not None:
        environment["PATH"] = os.pathsep.join(
            (str(node_executable.parent), environment.get("PATH", ""))
        )
    try:
        completed = subprocess.run(  # noqa: S603 -- resolved executable, fixed argv
            [str(path), PROBE_FLAGS[name]],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
            timeout=(
                PNPM_PROBE_TIMEOUT_SECONDS if name == "pnpm" else PROBE_TIMEOUT_SECONDS
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolchainError(f"cannot execute {name} version probe") from exc
    if completed.returncode != 0:
        raise ToolchainError(
            f"{name} version probe exited with status {completed.returncode}"
        )
    combined = "\n".join(
        part for part in (completed.stdout.strip(), completed.stderr.strip()) if part
    )
    version = parse_version_output(name, combined)
    expected = EXPECTED_VERSIONS[name]
    if version != expected:
        raise ToolchainError(
            f"{name} version mismatch: expected {expected}, observed {version}"
        )
    return ToolProbe(name=name, executable=path, version=version)


def _run_bounded_probe(executable: Path, argv: Sequence[str], label: str) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 -- resolved executable, fixed argv
            [str(executable), *argv],
            check=False,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolchainError(f"cannot execute {label} capability probe") from exc
    if completed.returncode != 0:
        raise ToolchainError(
            f"{label} capability probe exited with status {completed.returncode}"
        )
    return completed.stdout.strip()


def parse_numeric_version(value: str, label: str) -> tuple[int, int, int]:
    """Parse a numeric tool version without accepting ambiguous partials."""

    match = NUMERIC_VERSION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ToolchainError(f"{label} returned a non-numeric version")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def probe_container_runtime(docker: str | None) -> tuple[ToolProbe, ...]:
    """Require a reachable, supported Docker daemon and Compose plugin."""

    executable = resolve_executable(docker, "docker")
    engine_output = _run_bounded_probe(
        executable,
        ("version", "--format", "{{.Client.Version}}|{{.Server.Version}}"),
        "Docker Engine",
    )
    engine_versions = engine_output.split("|")
    if len(engine_versions) != DOCKER_ENGINE_VERSION_FIELDS or not all(engine_versions):
        raise ToolchainError("Docker Engine did not report client and server versions")
    client, server = engine_versions
    for label, version in (("Docker client", client), ("Docker server", server)):
        if parse_numeric_version(version, label) < MINIMUM_DOCKER_VERSION:
            raise ToolchainError(f"{label} must be >=24.0.0, observed {version}")

    compose = _run_bounded_probe(
        executable,
        ("compose", "version", "--short"),
        "Docker Compose",
    )
    if parse_numeric_version(compose, "Docker Compose") < MINIMUM_COMPOSE_VERSION:
        raise ToolchainError(f"Docker Compose must be >=2.24.0, observed {compose}")
    return (
        ToolProbe(name="docker-client", executable=executable, version=client),
        ToolProbe(name="docker-server", executable=executable, version=server),
        ToolProbe(name="docker-compose", executable=executable, version=compose),
    )


def _read_required_file(root: Path, relative_path: str) -> str:
    path = root / relative_path
    if path.is_symlink() or not path.is_file():
        raise ToolchainError(f"missing regular toolchain file: {relative_path}")
    return path.read_text(encoding="utf-8")


def _require_exact_pin(root: Path, relative_path: str, expected: str) -> None:
    observed = _read_required_file(root, relative_path).strip()
    if observed != expected:
        raise ToolchainError(
            f"{relative_path} pin mismatch: expected {expected}, observed {observed!r}"
        )


def _validate_uv_pin(pyproject: Mapping[str, object]) -> None:
    tool = pyproject.get("tool")
    uv_configuration = tool.get("uv") if isinstance(tool, dict) else None
    if (
        not isinstance(uv_configuration, dict)
        or uv_configuration.get("required-version") != f"=={EXPECTED_VERSIONS['uv']}"
    ):
        raise ToolchainError(
            f"pyproject.toml must require uv =={EXPECTED_VERSIONS['uv']}"
        )


def validate_repository_pins(root: Path) -> None:
    """Validate committed version declarations and frozen lock surfaces."""

    _require_exact_pin(root, ".python-version", EXPECTED_VERSIONS["python"])
    _require_exact_pin(root, ".node-version", EXPECTED_VERSIONS["node"])

    try:
        pyproject = tomllib.loads(_read_required_file(root, "pyproject.toml"))
    except tomllib.TOMLDecodeError as exc:
        raise ToolchainError("pyproject.toml is not valid TOML") from exc
    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise ToolchainError("pyproject.toml is missing [project]")
    requires_python = project.get("requires-python")
    if not isinstance(requires_python, str) or requires_python.replace(" ", "") != (
        ">=3.14.7,<3.15"
    ):
        raise ToolchainError("pyproject.toml must constrain Python to >=3.14.7,<3.15")
    _validate_uv_pin(pyproject)

    uv_lock = _read_required_file(root, "uv.lock")
    if not re.search(
        r'^requires-python\s*=\s*">=3\.14\.7,\s*<3\.15"\s*$',
        uv_lock,
        re.MULTILINE,
    ):
        raise ToolchainError("uv.lock does not preserve the Python 3.14.7 constraint")

    try:
        package = json.loads(_read_required_file(root, "package.json"))
    except json.JSONDecodeError as exc:
        raise ToolchainError("package.json is not valid JSON") from exc
    if not isinstance(package, dict):
        raise ToolchainError("package.json must contain a JSON object")
    expected_package_manager = f"pnpm@{EXPECTED_VERSIONS['pnpm']}"
    if package.get("packageManager") != expected_package_manager:
        raise ToolchainError(
            f"package.json must declare packageManager={expected_package_manager}"
        )
    engines = package.get("engines")
    if (
        not isinstance(engines, dict)
        or engines.get("pnpm") != (EXPECTED_VERSIONS["pnpm"])
    ):
        raise ToolchainError("package.json must pin the pnpm engine exactly")

    pnpm_lock = _read_required_file(root, "pnpm-lock.yaml")
    if not re.search(
        r"^lockfileVersion:\s*['\"]9\.0['\"]\s*$", pnpm_lock, re.MULTILINE
    ):
        raise ToolchainError("pnpm-lock.yaml is missing lockfileVersion 9.0")


def check_toolchain(  # noqa: PLR0913 -- explicit tool paths avoid an untyped map
    root: Path,
    *,
    python: str | None,
    node: str | None,
    uv: str | None,
    pnpm: str | None,
    docker: str | None = None,
    require_containers: bool = False,
) -> tuple[ToolProbe, ...]:
    """Validate pins and every executable, returning evidence on success."""

    validate_repository_pins(root)
    python_probe = probe_tool("python", python or sys.executable)
    node_probe = probe_tool("node", node)
    uv_probe = probe_tool("uv", uv)
    pnpm_probe = probe_tool(
        "pnpm",
        pnpm,
        node_executable=node_probe.executable,
    )
    probes: tuple[ToolProbe, ...] = (
        python_probe,
        node_probe,
        uv_probe,
        pnpm_probe,
    )
    if require_containers:
        probes += probe_container_runtime(docker)
    return probes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--python", dest="python_executable")
    parser.add_argument("--node", dest="node_executable")
    parser.add_argument("--uv", dest="uv_executable")
    parser.add_argument("--pnpm", dest="pnpm_executable")
    parser.add_argument("--docker", dest="docker_executable")
    parser.add_argument("--require-containers", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        probes = check_toolchain(
            args.root.resolve(),
            python=args.python_executable,
            node=args.node_executable,
            uv=args.uv_executable,
            pnpm=args.pnpm_executable,
            docker=args.docker_executable,
            require_containers=args.require_containers,
        )
    except (OSError, ToolchainError) as exc:
        print(f"TOOLCHAIN ERROR: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    versions = " ".join(f"{probe.name}={probe.version}" for probe in probes)
    print(f"TOOLCHAIN OK {versions}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
