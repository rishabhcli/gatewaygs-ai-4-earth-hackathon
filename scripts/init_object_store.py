#!/usr/bin/env python3
"""Idempotently establish the repository-owned local object bucket."""

from __future__ import annotations

import os
import stat
import time
from pathlib import Path

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import HTTPError as Urllib3HTTPError

REPOSITORY_NAME = "gatewaygs-ai-4-earth-hackathon"
BUCKET = "gatewaygs-ai-4-earth-hackathon"
ENDPOINT = "127.0.0.1:4176"
MINIMUM_CREDENTIAL_CHARACTERS = 32
SECRET_FILE_MODE = 0o600
MAXIMUM_SECRET_BYTES = 4096


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
        raise RuntimeError("object-store secret exceeds 4096 bytes")
    return encoded


def _trusted_directory(root: Path, path: Path, label: str) -> Path:
    if path.is_symlink():
        raise RuntimeError(f"{label} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"{label} does not exist") from error
    if not resolved.is_relative_to(root):
        raise RuntimeError(f"{label} escaped the repository trust boundary")
    if not resolved.is_dir():
        raise RuntimeError(f"{label} is not a directory")
    return resolved


def _secret_open_flags() -> tuple[int, int]:
    directory_flags = os.O_RDONLY
    file_flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        directory_flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        directory_flags |= os.O_NOFOLLOW
        file_flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        file_flags |= os.O_NONBLOCK
    return directory_flags, file_flags


def _validate_secret_descriptor(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise RuntimeError("object-store secret is not a regular file")
    if stat.S_IMODE(metadata.st_mode) != SECRET_FILE_MODE:
        raise RuntimeError("object-store secret permissions must be 0600")


def _open_secret_file(secrets_root: Path, filename: str) -> tuple[int, int]:
    directory_flags, file_flags = _secret_open_flags()
    directory = os.open(secrets_root, directory_flags)
    try:
        descriptor = os.open(filename, file_flags, dir_fd=directory)
    except OSError as exc:
        os.close(directory)
        raise RuntimeError("object-store secret must not be a symlink") from exc
    try:
        _validate_secret_descriptor(descriptor)
    except BaseException:
        os.close(descriptor)
        os.close(directory)
        raise
    return directory, descriptor


def _read_secret(root: Path, filename: str) -> str:
    repository_root = root.resolve(strict=True)
    if not repository_root.is_dir():
        raise RuntimeError("repository root is not a directory")
    dev_root = _trusted_directory(
        repository_root, root / ".dev", "development state directory"
    )
    secrets_root = _trusted_directory(
        repository_root, dev_root / "secrets", "secrets directory"
    )
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise RuntimeError("object-store secret path escaped its trust boundary")
    directory, descriptor = _open_secret_file(secrets_root, filename)
    try:
        encoded = _read_bounded(descriptor)
    finally:
        os.close(descriptor)
        os.close(directory)
    try:
        value = encoded.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("object-store secret must contain UTF-8 text") from exc
    if len(value) < MINIMUM_CREDENTIAL_CHARACTERS:
        raise RuntimeError("object-store credential is invalid")
    return value


def client(root: Path) -> Minio:
    return Minio(
        ENDPOINT,
        access_key=_read_secret(root, "minio_root_user"),
        secret_key=_read_secret(root, "minio_root_password"),
        secure=False,
    )


def ensure_bucket(timeout_seconds: float = 900.0) -> None:
    root = Path(__file__).resolve().parents[1]
    if root.name != REPOSITORY_NAME:
        raise RuntimeError("repository identity check failed")
    object_store = client(root)
    deadline = time.monotonic() + timeout_seconds
    last_error: S3Error | Urllib3HTTPError | OSError | None = None
    while time.monotonic() < deadline:
        try:
            if not object_store.bucket_exists(BUCKET):
                object_store.make_bucket(BUCKET)
            if object_store.bucket_exists(BUCKET):
                print("repository object bucket is ready")  # noqa: T201
                return
        except (S3Error, Urllib3HTTPError, OSError) as error:
            last_error = error
        time.sleep(0.5)
    raise RuntimeError(
        "object bucket did not become ready before timeout"
    ) from last_error


if __name__ == "__main__":
    ensure_bucket()
