#!/usr/bin/env python3
"""Own one repository-scoped foreground Compose service and its shutdown."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from scripts.devctl import DevctlError, resolve_compose_executable

PROJECT = "gatewaygs-ai-4-earth-hackathon"
ALLOWED_SERVICES = ("catalog", "minio")
STOP_TIMEOUT_SECONDS = 3
CHILD_EXIT_TIMEOUT_SECONDS = 5


def repository_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if root.name != PROJECT:
        raise RuntimeError("repository identity check failed")
    return root


def compose_prefix(root: Path) -> list[str]:
    root = root.resolve()
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker is required for the scoped Compose service")
    try:
        compose = resolve_compose_executable(docker, os.environ)
    except DevctlError as exc:
        raise RuntimeError("Docker Compose plugin is unavailable") from exc
    return [
        str(compose),
        "--project-name",
        PROJECT,
        "--env-file",
        str(root / "ports.env"),
        "--file",
        str(root / "compose.yaml"),
    ]


def compose_environment(root: Path) -> dict[str, str]:
    allowed_host = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "USER", "LOGNAME")
    environment = {key: os.environ[key] for key in allowed_host if key in os.environ}
    environment.setdefault("PATH", os.defpath)
    state = root / ".dev"
    environment.update(
        {
            "HOME": str(state / "home"),
            "TMPDIR": str(state / "tmp"),
            "XDG_CACHE_HOME": str(state / "cache"),
            "XDG_CONFIG_HOME": str(state / "config"),
            "XDG_DATA_HOME": str(state / "data"),
            "XDG_STATE_HOME": str(state / "state"),
            "DOCKER_CONFIG": str(state / "config" / "docker"),
            "COMPOSE_PROJECT_NAME": PROJECT,
        }
    )
    return environment


def require_compose_inputs(root: Path) -> None:
    for path in (root / "ports.env", root / "compose.yaml"):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(
                f"Compose input must be a regular repository file: {path}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=ALLOWED_SERVICES)
    return parser.parse_args()


def stop_service(root: Path, service: str) -> None:
    require_compose_inputs(root)
    result = subprocess.run(  # noqa: S603 - argv is a closed service allowlist
        [
            *compose_prefix(root),
            "stop",
            "--timeout",
            str(STOP_TIMEOUT_SECONDS),
            service,
        ],
        cwd=root,
        env=compose_environment(root),
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=STOP_TIMEOUT_SECONDS + 2,
    )
    if result.returncode != 0:
        raise RuntimeError(f"scoped Compose stop failed for {service}")


def run(service: str) -> int:
    root = repository_root()
    if os.environ.get("COMPOSE_PROJECT_NAME") != PROJECT:
        raise RuntimeError("COMPOSE_PROJECT_NAME is missing or foreign")

    require_compose_inputs(root)
    command = [*compose_prefix(root), "up", "--no-deps"]
    if service == "minio":
        command.append("--build")
    command.append(service)
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    process = subprocess.Popen(  # noqa: S603 - argv is a closed service allowlist
        command,
        cwd=root,
        env=compose_environment(root),
        stdin=subprocess.DEVNULL,
    )
    try:
        while not stopping:
            return_code = process.poll()
            if return_code is not None:
                return return_code
            time.sleep(0.1)
        stop_service(root, service)
        try:
            return process.wait(timeout=CHILD_EXIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.terminate()
            return process.wait(timeout=CHILD_EXIT_TIMEOUT_SECONDS)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=CHILD_EXIT_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=CHILD_EXIT_TIMEOUT_SECONDS)


def main() -> int:
    return run(parse_args().service)


if __name__ == "__main__":
    raise SystemExit(main())
