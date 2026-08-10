#!/usr/bin/env python3
"""Create strong local-only credentials without exposing their values."""

from __future__ import annotations

import argparse
import os
import secrets
import stat
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


REPOSITORY_NAME = "gatewaygs-ai-4-earth-hackathon"
SECRET_LENGTH = 48
SECRET_FILE_MODE = 0o600
SECRETS_DIRECTORY_MODE = 0o700
MINIMUM_SECRET_CHARACTERS = 32
MAXIMUM_SECRET_BYTES = 4096


def _open_real_directory(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(
            f"secret directory must be a real directory: {path}"
        ) from exc
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise RuntimeError(f"secret directory must be a real directory: {path}")
    return descriptor


def _read_bounded(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    remaining = MAXIMUM_SECRET_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    encoded = b"".join(chunks)
    if len(encoded) > MAXIMUM_SECRET_BYTES:
        raise RuntimeError("secret exceeds 4096 bytes")
    return encoded


def repository_root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if root.name != REPOSITORY_NAME:
        raise RuntimeError("repository identity check failed")
    return root


def _write_new_secret(path: Path, value: str) -> None:
    directory = _open_real_directory(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path.name, flags, SECRET_FILE_MODE, dir_fd=directory)
        try:
            os.write(descriptor, f"{value}\n".encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def _validate_existing_secret(path: Path) -> None:
    directory = _open_real_directory(path.parent)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        try:
            descriptor = os.open(path.name, flags, dir_fd=directory)
        except OSError as exc:
            raise RuntimeError(
                f"secret path must not be a symlink: {path.name}"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"secret path is not a regular file: {path.name}")
            mode = stat.S_IMODE(metadata.st_mode)
            if mode != SECRET_FILE_MODE:
                raise RuntimeError(f"secret permissions must be 0600: {path.name}")
            encoded = _read_bounded(descriptor)
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)
    try:
        value = encoded.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"secret must contain UTF-8 text: {path.name}") from exc
    if len(value) < MINIMUM_SECRET_CHARACTERS:
        raise RuntimeError(f"secret is shorter than 32 characters: {path.name}")


def _validate_existing_directory(root: Path, path: Path, label: str) -> None:
    """Refuse redirected or non-directory state before any filesystem mutation."""
    if path.is_symlink():
        raise RuntimeError(f"{label} must not be a symlink")
    if not path.exists():
        return
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"{label} escaped the repository trust boundary")
    if not resolved.is_dir():
        raise RuntimeError(f"{label} is not a directory")


def ensure() -> None:
    root = repository_root()
    dev_dir = root / ".dev"
    secrets_dir = dev_dir / "secrets"

    # Validate every existing pathname before mkdir/chmod can follow a redirect.
    _validate_existing_directory(root, dev_dir, "development state directory")
    _validate_existing_directory(root, secrets_dir, "secrets directory")
    dev_dir.mkdir(exist_ok=True)
    secrets_dir.mkdir(exist_ok=True, mode=SECRETS_DIRECTORY_MODE)
    secrets_dir.chmod(SECRETS_DIRECTORY_MODE)

    generators: dict[str, Callable[[], str]] = {
        "postgres_password": lambda: secrets.token_urlsafe(SECRET_LENGTH),
        "minio_root_user": lambda: f"local-{secrets.token_hex(16)}",
        "minio_root_password": lambda: secrets.token_urlsafe(SECRET_LENGTH),
    }
    for filename, generator in generators.items():
        path = secrets_dir / filename
        if not path.exists():
            _write_new_secret(path, generator())
        _validate_existing_secret(path)
    print("development secret files are present with mode 0600")  # noqa: T201


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("ensure",))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "ensure":
        ensure()


if __name__ == "__main__":
    main()
