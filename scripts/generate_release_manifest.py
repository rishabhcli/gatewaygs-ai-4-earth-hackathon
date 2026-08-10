#!/usr/bin/env python3
"""Generate deterministic CycloneDX inventories and a release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


PROJECT_NAME = "gatewaygs-ai-4-earth-hackathon"
PROJECT_VERSION = "0.1.0"
SYFT_VERSION = "1.49.0"
CYCLONEDX_SPEC_VERSION = "1.7"
CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.7.schema.json"
DOCKER_SOCKET_ENDPOINT = "unix:///var/run/docker.sock"
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
MINIO_IMAGE = "gatewaygs-ai-4-earth-hackathon/minio:RELEASE.2025-10-15T17-29-55Z"
POSTGIS_IMAGE = (
    "postgis/postgis:16-3.5-alpine@"
    "sha256:d2fe6296c8ed5b21b31a426f51b9176b4d89f80a0a380632a7a833d604951273"
)
MAX_COMMAND_OUTPUT_BYTES = 64 * 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 300.0
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
TOOL_ENVIRONMENT_PASSTHROUGH = (
    "HOME",
    "PATH",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
)
EXPECTED_OUTPUTS = frozenset(
    {
        "application-locks.cdx.json",
        "minio-image.cdx.json",
        "postgis-image.cdx.json",
        "release-manifest.json",
    }
)
TEMPORARY_OUTPUTS = frozenset(f".{name}.tmp" for name in EXPECTED_OUTPUTS)
RELEASE_INPUTS = (
    ".dockerignore",
    ".node-version",
    ".python-version",
    "Makefile",
    "apps/web/index.html",
    "apps/web/package.json",
    "apps/web/playwright.config.ts",
    "apps/web/tsconfig.json",
    "apps/web/vite.config.ts",
    "compose.yaml",
    "infra/minio/Dockerfile",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "scripts/generate_release_manifest.py",
    "uv.lock",
)
RELEASE_INPUT_DIRECTORIES = (
    "apps/web/public",
    "apps/web/src",
    "apps/web/tests",
)


class ReleaseManifestError(RuntimeError):
    """A safe, deterministic release-manifest failure."""


@dataclass(frozen=True)
class NormalizedBom:
    data: bytes
    component_count: int


def _require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReleaseManifestError(f"{label} must be a JSON object")
    return value


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ReleaseManifestError(f"{label} must be a JSON array")
    return value


def _canonicalize(value: object) -> object:
    """Sort JSON objects and set-like arrays into a stable representation."""

    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ReleaseManifestError("CycloneDX contains a non-string object key")
        return {
            key: _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: pair[0])
        }
    if isinstance(value, list):
        items = [_canonicalize(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    if value is None or isinstance(value, bool | int | float | str):
        return value
    raise ReleaseManifestError("CycloneDX contains an unsupported JSON value")


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            _canonicalize(value),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _validate_syft_metadata(metadata: dict[str, object]) -> None:
    tools = _require_object(metadata.get("tools"), "CycloneDX metadata.tools")
    components = _require_list(
        tools.get("components"), "CycloneDX metadata.tools.components"
    )
    syft_versions = {
        component.get("version")
        for raw_component in components
        for component in (_require_object(raw_component, "CycloneDX tool"),)
        if component.get("name") == "syft"
    }
    if syft_versions != {SYFT_VERSION}:
        raise ReleaseManifestError(
            f"CycloneDX must be generated only by Syft {SYFT_VERSION}"
        )


def _relativize_checkout_paths(value: object, checkout_root: Path) -> object:
    """Remove the checkout location from every root-prefixed CycloneDX value."""

    resolved_root = checkout_root.resolve(strict=True)
    if resolved_root == resolved_root.parent:
        raise ReleaseManifestError("the filesystem root cannot be an SBOM checkout")
    root_text = resolved_root.as_posix().rstrip("/")
    root_prefix = f"{root_text}/"

    def relativize(item: object) -> object:
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ReleaseManifestError("CycloneDX contains a non-string object key")
            return {key: relativize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [relativize(child) for child in item]
        if isinstance(item, str):
            if item == root_text:
                return "."
            if item.startswith(root_prefix):
                return item.removeprefix(root_prefix)
            if root_text in item:
                raise ReleaseManifestError(
                    "CycloneDX contains a checkout path in an unsupported "
                    "field encoding"
                )
        return item

    return relativize(value)


def _normalize_application_source_reference(
    payload: dict[str, object],
    metadata: dict[str, object],
) -> dict[str, object]:
    source = _require_object(metadata.get("component"), "CycloneDX metadata.component")
    expected: Mapping[str, str] = {
        "type": "file",
        "name": PROJECT_NAME,
        "version": PROJECT_VERSION,
    }
    for key, expected_value in expected.items():
        if source.get(key) != expected_value:
            raise ReleaseManifestError(
                f"CycloneDX application source {key} drifted from {expected_value!r}"
            )
    observed_reference = source.get("bom-ref")
    if not isinstance(observed_reference, str) or not observed_reference:
        raise ReleaseManifestError("CycloneDX application source bom-ref is missing")
    stable_reference = f"source:{PROJECT_NAME}@{PROJECT_VERSION}"

    def replace_reference(item: object) -> object:
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ReleaseManifestError("CycloneDX contains a non-string object key")
            return {key: replace_reference(child) for key, child in item.items()}
        if isinstance(item, list):
            return [replace_reference(child) for child in item]
        if item == observed_reference:
            return stable_reference
        return item

    return _require_object(replace_reference(payload), "normalized CycloneDX document")


def normalize_cyclonedx(
    raw: str,
    *,
    checkout_root: Path | None = None,
) -> NormalizedBom:
    """Validate Syft's schema and remove volatile and host-specific identity."""

    try:
        payload = _require_object(json.loads(raw), "CycloneDX document")
    except json.JSONDecodeError as exc:
        raise ReleaseManifestError("Syft output is not valid JSON") from exc
    expected_scalars: Mapping[str, object] = {
        "$schema": CYCLONEDX_SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "version": 1,
    }
    for key, expected in expected_scalars.items():
        if payload.get(key) != expected:
            raise ReleaseManifestError(
                f"CycloneDX {key} drifted from the supported value {expected!r}"
            )
    serial_number = payload.pop("serialNumber", None)
    if not isinstance(serial_number, str) or not serial_number.startswith("urn:uuid:"):
        raise ReleaseManifestError("CycloneDX serialNumber is missing or malformed")
    metadata = _require_object(payload.get("metadata"), "CycloneDX metadata")
    timestamp = metadata.pop("timestamp", None)
    if not isinstance(timestamp, str) or not timestamp:
        raise ReleaseManifestError("CycloneDX metadata timestamp is missing")
    _validate_syft_metadata(metadata)
    components = _require_list(payload.get("components"), "CycloneDX components")
    if not components:
        raise ReleaseManifestError("CycloneDX inventory contains no components")
    _require_list(payload.get("dependencies"), "CycloneDX dependencies")
    if checkout_root is not None:
        payload = _normalize_application_source_reference(payload, metadata)
        payload = _require_object(
            _relativize_checkout_paths(payload, checkout_root),
            "normalized CycloneDX document",
        )
    return NormalizedBom(
        data=_canonical_json(payload),
        component_count=len(components),
    )


def _resolve_executable(value: str | None, name: str) -> Path:
    candidate = value or shutil.which(name)
    if not candidate:
        raise ReleaseManifestError(f"required release tool is unavailable: {name}")
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        resolved = shutil.which(str(path))
        if resolved is None:
            raise ReleaseManifestError(f"required release tool is unavailable: {name}")
        path = Path(resolved)
    path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ReleaseManifestError(f"release tool is not executable: {name}")
    return path


def _run_command(
    executable: Path,
    argv: Sequence[str],
    label: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 -- resolved executable, fixed argv
            [str(executable), *argv],
            check=False,
            capture_output=True,
            env=environment,
            text=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseManifestError(
            f"{label} did not complete within its boundary"
        ) from exc
    if completed.returncode != 0:
        raise ReleaseManifestError(
            f"{label} exited with status {completed.returncode}; output withheld"
        )
    if len(completed.stdout) > MAX_COMMAND_OUTPUT_BYTES:
        raise ReleaseManifestError(f"{label} exceeded the 64 MiB output limit")
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseManifestError(f"{label} output is not UTF-8") from exc


def _base_tool_environment() -> dict[str, str]:
    environment = {
        name: value
        for name in TOOL_ENVIRONMENT_PASSTHROUGH
        if (value := os.environ.get(name))
    }
    environment.update(
        {
            "DOCKER_HOST": DOCKER_SOCKET_ENDPOINT,
            "LANG": "C",
            "LC_ALL": "C",
            "TEMP": str(REPOSITORY_ROOT / ".dev" / "tmp"),
            "TMP": str(REPOSITORY_ROOT / ".dev" / "tmp"),
            "TMPDIR": str(REPOSITORY_ROOT / ".dev" / "tmp"),
            "TZ": "UTC",
        }
    )
    return environment


def _syft_environment() -> dict[str, str]:
    environment = _base_tool_environment()
    environment.update(
        {
            "SYFT_CHECK_FOR_APP_UPDATE": "false",
            "SYFT_PARALLELISM": "1",
        }
    )
    return environment


def _verify_syft(syft: Path) -> None:
    observed = _run_command(
        syft,
        ("--version",),
        "Syft version probe",
        environment=_syft_environment(),
    ).strip()
    if observed != f"syft {SYFT_VERSION}":
        raise ReleaseManifestError(
            f"Syft version mismatch: expected {SYFT_VERSION}, observed {observed!r}"
        )


def _scan_application_locks(root: Path, syft: Path) -> NormalizedBom:
    raw = _run_command(
        syft,
        (
            "scan",
            "--config",
            os.devnull,
            f"dir:{root}",
            "--quiet",
            "--parallelism",
            "1",
            "--override-default-catalogers",
            "javascript-lock-cataloger,python-package-cataloger",
            "--exclude",
            "./.dev/**",
            "--exclude",
            "./.venv/**",
            "--exclude",
            "./node_modules/**",
            "--source-name",
            PROJECT_NAME,
            "--source-version",
            PROJECT_VERSION,
            "--output",
            "cyclonedx-json",
        ),
        "application lock SBOM scan",
        environment=_syft_environment(),
    )
    return normalize_cyclonedx(raw, checkout_root=root)


def _scan_image(syft: Path, image: str, label: str) -> NormalizedBom:
    raw = _run_command(
        syft,
        (
            "scan",
            "--config",
            os.devnull,
            f"docker:{image}",
            "--quiet",
            "--parallelism",
            "1",
            "--output",
            "cyclonedx-json",
        ),
        f"{label} image SBOM scan",
        environment=_syft_environment(),
    )
    return normalize_cyclonedx(raw)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_descriptor(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise ReleaseManifestError(f"release input must be a regular file: {relative}")
    data = path.read_bytes()
    return {"path": relative, "bytes": len(data), "sha256": _sha256(data)}


def _directory_descriptor(root: Path, relative: str) -> dict[str, object]:
    directory = root / relative
    if directory.is_symlink() or not directory.is_dir():
        raise ReleaseManifestError(f"built artifact directory is missing: {relative}")
    files: list[dict[str, object]] = []
    total_bytes = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ReleaseManifestError(
                f"built artifact contains a symlink: {path.relative_to(root)}"
            )
        if not path.is_file():
            continue
        data = path.read_bytes()
        total_bytes += len(data)
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": len(data),
                "sha256": _sha256(data),
                "mode": f"{path.stat().st_mode & 0o777:04o}",
            }
        )
    if not files:
        raise ReleaseManifestError(f"built artifact directory is empty: {relative}")
    inventory = _canonical_json(files)
    return {
        "kind": "directory",
        "path": relative,
        "files": files,
        "file_count": len(files),
        "bytes": total_bytes,
        "tree_sha256": _sha256(inventory),
    }


def _image_descriptor(
    docker: Path,
    image_reference: str,
    label: str,
) -> dict[str, object]:
    raw = _run_command(
        docker,
        ("image", "inspect", "--format", "{{json .}}", image_reference),
        f"{label} image inspection",
        environment=_base_tool_environment(),
    )
    try:
        image = _require_object(json.loads(raw), "Docker image inspection")
    except json.JSONDecodeError as exc:
        raise ReleaseManifestError("Docker image inspection is not valid JSON") from exc
    image_id = image.get("Id")
    if not isinstance(image_id, str) or SHA256_PATTERN.fullmatch(image_id) is None:
        raise ReleaseManifestError("Docker image ID is missing or malformed")
    architecture = image.get("Architecture")
    operating_system = image.get("Os")
    if not isinstance(architecture, str) or not isinstance(operating_system, str):
        raise ReleaseManifestError("Docker image platform metadata is missing")
    raw_digests = _require_list(image.get("RepoDigests", []), "Docker RepoDigests")
    repo_digests: list[str] = []
    for item in raw_digests:
        if not isinstance(item, str):
            raise ReleaseManifestError("Docker RepoDigests contains a non-string value")
        repo_digests.append(item)
    config = _require_object(image.get("Config"), "Docker image Config")
    labels = _require_object(config.get("Labels", {}), "Docker image labels")
    oci_labels = {
        key: value
        for key, value in labels.items()
        if key.startswith("org.opencontainers.image.") and isinstance(value, str)
    }
    return {
        "kind": "oci-image",
        "reference": image_reference,
        "image_id": image_id,
        "repo_digests": sorted(repo_digests),
        "platform": f"{operating_system}/{architecture}",
        "oci_labels": oci_labels,
    }


def generate_bundle(root: Path, syft: Path, docker: Path) -> dict[str, bytes]:
    """Generate one in-memory release bundle from built artifacts."""

    _verify_syft(syft)
    application_bom = _scan_application_locks(root, syft)
    minio_bom = _scan_image(syft, MINIO_IMAGE, "MinIO")
    postgis_bom = _scan_image(syft, POSTGIS_IMAGE, "PostGIS")
    web_artifact = _directory_descriptor(root, "apps/web/dist")
    minio_artifact = _image_descriptor(docker, MINIO_IMAGE, "MinIO")
    postgis_artifact = _image_descriptor(docker, POSTGIS_IMAGE, "PostGIS")
    manifest: dict[str, object] = {
        "schema_version": 1,
        "project": PROJECT_NAME,
        "project_version": PROJECT_VERSION,
        "status": "local-release-artifacts-not-production",
        "scope": (
            "Tier 0 web build and local Compose runtime images; API and worker "
            "processes run from source and are not packaged release artifacts"
        ),
        "command": "make sbom",
        "seed": None,
        "generator": {
            "name": "syft",
            "version": SYFT_VERSION,
            "cyclonedx_spec_version": CYCLONEDX_SPEC_VERSION,
            "normalization": (
                "remove volatile serial/timestamp; relativize checkout-root paths; "
                "canonical JSON arrays"
            ),
        },
        "inputs": [
            *[_file_descriptor(root, path) for path in RELEASE_INPUTS],
            *[_directory_descriptor(root, path) for path in RELEASE_INPUT_DIRECTORIES],
        ],
        "artifacts": [web_artifact, minio_artifact, postgis_artifact],
        "sboms": [
            {
                "path": "application-locks.cdx.json",
                "scope": "locked Python and npm application dependencies",
                "components": application_bom.component_count,
                "sha256": _sha256(application_bom.data),
            },
            {
                "path": "minio-image.cdx.json",
                "scope": "built local MinIO OCI image",
                "components": minio_bom.component_count,
                "sha256": _sha256(minio_bom.data),
            },
            {
                "path": "postgis-image.cdx.json",
                "scope": "pinned third-party PostGIS OCI runtime image",
                "components": postgis_bom.component_count,
                "sha256": _sha256(postgis_bom.data),
            },
        ],
    }
    return {
        "application-locks.cdx.json": application_bom.data,
        "minio-image.cdx.json": minio_bom.data,
        "postgis-image.cdx.json": postgis_bom.data,
        "release-manifest.json": _canonical_json(manifest),
    }


def _write_bundle(root: Path, output_dir: Path, bundle: Mapping[str, bytes]) -> None:
    development_root = root / ".dev"
    if development_root.is_symlink():
        raise ReleaseManifestError(".dev must not be a symlink")
    development_root.mkdir(parents=True, exist_ok=True)
    development_root.chmod(0o700)
    development_root = development_root.resolve(strict=True)
    if output_dir.is_symlink():
        raise ReleaseManifestError("release output directory must not be a symlink")
    destination = output_dir.resolve(strict=False)
    if not destination.is_relative_to(development_root):
        raise ReleaseManifestError("release output must remain below .dev/")
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    unexpected = {
        path.name
        for path in destination.iterdir()
        if path.name not in EXPECTED_OUTPUTS | TEMPORARY_OUTPUTS
    }
    if unexpected:
        raise ReleaseManifestError(
            "release output contains unexpected files: " + ", ".join(sorted(unexpected))
        )
    if set(bundle) != EXPECTED_OUTPUTS:
        raise ReleaseManifestError(
            "release generator returned an incomplete output set"
        )
    for name, data in sorted(bundle.items()):
        destination_path = destination / name
        if destination_path.is_symlink():
            raise ReleaseManifestError(f"release output must not be a symlink: {name}")
        temporary = destination / f".{name}.tmp"
        if temporary.is_symlink():
            raise ReleaseManifestError(f"release temporary path is a symlink: {name}")
        temporary.write_bytes(data)
        temporary.chmod(0o644)
        temporary.replace(destination_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--root", type=Path, default=root)
    parser.add_argument("--output-dir", type=Path, default=root / ".dev" / "release")
    parser.add_argument("--syft")
    parser.add_argument("--docker")
    parser.add_argument("--verify-reproducible", action="store_true")
    return parser


def _require_reproducible(
    first: Mapping[str, bytes], second: Mapping[str, bytes]
) -> None:
    if first == second:
        return
    changed = sorted(
        name for name in EXPECTED_OUTPUTS if first.get(name) != second.get(name)
    )
    raise ReleaseManifestError(
        "release generation is not reproducible: " + ", ".join(changed)
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        root = arguments.root.resolve(strict=True)
        syft = _resolve_executable(arguments.syft, "syft")
        docker = _resolve_executable(arguments.docker, "docker")
        first = generate_bundle(root, syft, docker)
        if arguments.verify_reproducible:
            second = generate_bundle(root, syft, docker)
            _require_reproducible(first, second)
        _write_bundle(root, arguments.output_dir, first)
    except (OSError, ReleaseManifestError) as exc:
        print(f"RELEASE MANIFEST ERROR: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    hashes = " ".join(f"{name}={_sha256(data)}" for name, data in sorted(first.items()))
    print(f"RELEASE MANIFEST OK {hashes}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
