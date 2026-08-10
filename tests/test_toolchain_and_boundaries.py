from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import check_boundaries, check_toolchain, generate_release_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SBOM_COUNT = 3
SECURE_DIRECTORY_MODE = 0o700
WORLD_READABLE_DIRECTORY_MODE = 0o755
CONTROL_ENVIRONMENT_EXACT_NAMES = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONWARNINGS",
        "PYTEST_ADDOPTS",
        "NODE_OPTIONS",
        "NODE_PATH",
        "BASH_ENV",
        "ENV",
        "NODE_BINARY",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
    }
)
CONTROL_ENVIRONMENT_PREFIXES = (
    "COVERAGE_",
    "NPM_CONFIG_",
    "npm_config_",
    "PNPM_CONFIG_",
    "pnpm_config_",
    "UV_",
    "PLAYWRIGHT_",
    "DOCKER_",
    "COMPOSE_",
    "BUILDKIT_",
    "SYFT_",
    "MYPY_",
    "RUFF_",
    "VITE_",
    "LD_",
    "DYLD_",
)
REQUIRED_TARGETS = frozenset(
    {
        "bootstrap",
        "check",
        "lint",
        "format",
        "format-check",
        "typecheck",
        "test",
        "test-integration",
        "test-e2e",
        "eval",
        "build",
        "reset-tier0-state",
        "run-local",
        "release-check",
        "verify-all",
        "dev:preflight",
        "dev:up",
        "dev:health",
        "dev:down",
    }
)


def _write_domain_module(root: Path, source: str) -> Path:
    _write_domain_ownership(root)
    module = root / "packages" / "retrieval" / "module.py"
    module.write_text(source, encoding="utf-8")
    return module


def _write_domain_ownership(root: Path) -> None:
    for name in check_boundaries.DOMAIN_PACKAGE_NAMES:
        package = root / "packages" / name
        package.mkdir(parents=True, exist_ok=True)
        ownership = package / "OWNERSHIP.md"
        if not ownership.exists():
            ownership.write_text(
                f"# {name.capitalize()} ownership\n\n"
                "Owns its named framework-independent domain contracts, explicit "
                "invariants, failure states, and versioned provenance. Application, "
                "transport, persistence, cloud, and mutable framework state remain "
                "outside this package boundary.\n",
                encoding="utf-8",
            )


def _write_executable(path: Path, output: str) -> Path:
    path.write_text(
        f"#!/usr/bin/env python3\nprint({output!r})\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_docker_executable(
    path: Path,
    *,
    client: str = "29.6.2",
    server: str = "29.6.2",
    compose: str = "5.3.1",
) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:3] == ['version', '--format']:\n"
        f"    print({f'{client}|{server}'!r})\n"
        "elif sys.argv[1:] == ['compose', 'version', '--short']:\n"
        f"    print({compose!r})\n"
        "else:\n"
        "    raise SystemExit(64)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _copy_toolchain_surface(destination: Path) -> None:
    for relative in (
        ".python-version",
        ".node-version",
        "pyproject.toml",
        "uv.lock",
        "package.json",
        "pnpm-lock.yaml",
    ):
        (destination / relative).write_text(
            (REPOSITORY_ROOT / relative).read_text(encoding="utf-8"),
            encoding="utf-8",
        )


def _cyclonedx_payload(component_name: str) -> dict[str, object]:
    reference = f"pkg:generic/{component_name}@1.0.0"
    return {
        "$schema": generate_release_manifest.CYCLONEDX_SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": generate_release_manifest.CYCLONEDX_SPEC_VERSION,
        "serialNumber": "urn:uuid:volatile",
        "version": 1,
        "metadata": {
            "timestamp": "volatile",
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "syft",
                        "version": generate_release_manifest.SYFT_VERSION,
                    }
                ]
            },
            "component": {
                "type": "application",
                "name": component_name,
                "bom-ref": component_name,
            },
        },
        "components": [
            {
                "type": "library",
                "name": component_name,
                "version": "1.0.0",
                "bom-ref": reference,
                "purl": reference,
            }
        ],
        "dependencies": [{"ref": reference, "dependsOn": []}],
    }


def _write_fake_syft(path: Path) -> Path:
    application_payload = _cyclonedx_payload("application-lock")
    application_metadata = application_payload["metadata"]
    assert isinstance(application_metadata, dict)
    application_metadata["component"] = {
        "type": "file",
        "name": generate_release_manifest.PROJECT_NAME,
        "version": generate_release_manifest.PROJECT_VERSION,
        "bom-ref": "replaced-at-runtime",
    }
    application = json.dumps(application_payload, sort_keys=True)
    image = json.dumps(_cyclonedx_payload("minio-image"), sort_keys=True)
    postgis = json.dumps(_cyclonedx_payload("postgis-image"), sort_keys=True)
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import hashlib\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        f"    print('syft {generate_release_manifest.SYFT_VERSION}')\n"
        "elif sys.argv[1] == 'scan':\n"
        f"    payload = json.loads({application!r})\n"
        "    if any(item.startswith('docker:') for item in sys.argv):\n"
        f"        payload = json.loads({image!r})\n"
        "        if any('postgis/postgis:' in item for item in sys.argv):\n"
        f"            payload = json.loads({postgis!r})\n"
        "    else:\n"
        "        root = next(\n"
        "            item[4:] for item in sys.argv if item.startswith('dir:')\n"
        "        )\n"
        "        payload['metadata']['component']['bom-ref'] = (\n"
        "            hashlib.sha256(root.encode()).hexdigest()[:16]\n"
        "        )\n"
        "        payload['components'].append({\n"
        "            'type': 'file',\n"
        "            'name': root + '/pnpm-lock.yaml',\n"
        "            'bom-ref': root + '/pnpm-lock.yaml',\n"
        "        })\n"
        "        payload['dependencies'].append({\n"
        "            'ref': root + '/pnpm-lock.yaml',\n"
        "            'dependsOn': [],\n"
        "        })\n"
        "    payload['serialNumber'] = f'urn:uuid:{os.getpid()}'\n"
        "    payload['metadata']['timestamp'] = str(os.getpid())\n"
        "    print(json.dumps(payload))\n"
        "else:\n"
        "    raise SystemExit(64)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_fake_release_docker(path: Path) -> Path:
    minio_image = {
        "Id": "sha256:" + ("a" * 64),
        "Architecture": "amd64",
        "Os": "linux",
        "RepoDigests": ["example.invalid/minio@sha256:" + ("b" * 64)],
        "Config": {
            "Labels": {
                "org.opencontainers.image.version": "test",
                "com.docker.compose.version": "host-specific-ignored",
            }
        },
    }
    postgis_image = {
        "Id": "sha256:" + ("c" * 64),
        "Architecture": "amd64",
        "Os": "linux",
        "RepoDigests": ["postgis/postgis@sha256:" + ("d" * 64)],
        "Config": {
            "Labels": {
                "org.opencontainers.image.version": "16-3.5-alpine",
                "com.docker.compose.project": "host-specific-ignored",
            }
        },
    }
    images = {
        generate_release_manifest.MINIO_IMAGE: minio_image,
        generate_release_manifest.POSTGIS_IMAGE: postgis_image,
    }
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import sys\n"
        "if sys.argv[1:3] == ['image', 'inspect']:\n"
        f"    print(json.dumps({images!r}[sys.argv[-1]]))\n"
        "else:\n"
        "    raise SystemExit(64)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_fake_reset_docker(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['FAKE_LOG'], 'a', encoding='utf-8') as stream:\n"
        "    stream.write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['volume', 'ls']:\n"
        "    name = args[-1].removeprefix('name=^').removesuffix('$')\n"
        "    if os.environ.get('FAKE_VOLUME_MODE') == 'foreign':\n"
        "        print(name + '-backup')\n"
        "    else:\n"
        "        print(name)\n"
        "elif args[:2] == ['volume', 'rm']:\n"
        "    pass\n"
        "elif args and args[0] == 'compose' and 'ps' in args:\n"
        "    if os.environ.get('FAKE_CONTAINERS') == 'present':\n"
        "        print('repository-container-id')\n"
        "elif args and args[0] == 'compose' and 'down' in args:\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit(64)\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_release_surface(root: Path) -> None:
    for relative in generate_release_manifest.RELEASE_INPUTS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"release input {relative}\n", encoding="utf-8")
    for relative in generate_release_manifest.RELEASE_INPUT_DIRECTORIES:
        path = root / relative / "release-input.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"release input directory {relative}\n", encoding="utf-8")
    asset = root / "apps" / "web" / "dist" / "assets" / "application.js"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_text("export const ready = true;\n", encoding="utf-8")


def _make_phony_surface(makefile: str) -> str:
    lines = makefile.splitlines()
    start = next(
        index for index, line in enumerate(lines) if line.startswith(".PHONY:")
    )
    surface = [lines[start]]
    while surface[-1].endswith("\\"):
        surface.append(lines[start + len(surface)])
    return "\n".join(surface)


def _make_test_environment(
    updates: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in CONTROL_ENVIRONMENT_EXACT_NAMES
        and not name.startswith(CONTROL_ENVIRONMENT_PREFIXES)
    }
    environment.update(updates or {})
    return environment


def _tier0_evidence_payload(kind: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "kind": kind,
        "command": "make verify-all",
        "seed": None,
        "inputs": {"git_commit": "a" * 40},
        "tool_versions": {"gnu-make": "3.81"},
    }
    if kind == "tier0-ci-run":
        payload.update(
            {
                "run_url": "https://github.com/example/project/actions/runs/1",
                "conclusion": "success",
            }
        )
    else:
        payload.update(
            {
                "clean_checkout": True,
                "exit_code": 0,
                "output": "EVAL OK: no domain metric artifacts at Tier 0\n",
            }
        )
    return payload


@pytest.mark.parametrize(
    ("name", "output", "expected"),
    [
        ("python", "Python 3.14.7\n", "3.14.7"),
        ("node", "v24.19.0\n", "24.19.0"),
        ("uv", "uv 0.12.3 (build metadata)\n", "0.12.3"),
        ("pnpm", "11.21.0\n", "11.21.0"),
    ],
)
def test_version_output_is_parsed_strictly(
    name: str,
    output: str,
    expected: str,
) -> None:
    assert check_toolchain.parse_version_output(name, output) == expected


@pytest.mark.parametrize(
    ("name", "output"),
    [
        ("python", "Python 3.14"),
        ("node", "node v24.19.0"),
        ("uv", "0.12.3"),
        ("pnpm", "11.21.0\nextra"),
    ],
)
def test_malformed_version_output_fails_closed(name: str, output: str) -> None:
    with pytest.raises(check_toolchain.ToolchainError):
        check_toolchain.parse_version_output(name, output)


def test_repository_toolchain_pins_are_coherent() -> None:
    check_toolchain.validate_repository_pins(REPOSITORY_ROOT)


def test_complete_toolchain_probe_accepts_only_exact_versions(tmp_path: Path) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    python = _write_executable(binaries / "python", "Python 3.14.7")
    node = _write_executable(binaries / "node", "v24.19.0")
    uv = _write_executable(binaries / "uv", "uv 0.12.3 test-build")
    pnpm = _write_executable(binaries / "pnpm", "11.21.0")

    probes = check_toolchain.check_toolchain(
        REPOSITORY_ROOT,
        python=str(python),
        node=str(node),
        uv=str(uv),
        pnpm=str(pnpm),
    )

    assert {probe.name: probe.version for probe in probes} == {
        "python": "3.14.7",
        "node": "24.19.0",
        "uv": "0.12.3",
        "pnpm": "11.21.0",
    }


def test_complete_toolchain_probe_rejects_one_drifted_tool(tmp_path: Path) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    python = _write_executable(binaries / "python", "Python 3.14.7")
    node = _write_executable(binaries / "node", "v24.19.0")
    uv = _write_executable(binaries / "uv", "uv 0.12.2")
    pnpm = _write_executable(binaries / "pnpm", "11.21.0")

    with pytest.raises(check_toolchain.ToolchainError, match="uv version mismatch"):
        check_toolchain.check_toolchain(
            REPOSITORY_ROOT,
            python=str(python),
            node=str(node),
            uv=str(uv),
            pnpm=str(pnpm),
        )


def test_container_runtime_probe_requires_reachable_supported_capabilities(
    tmp_path: Path,
) -> None:
    docker = _write_docker_executable(tmp_path / "docker")

    probes = check_toolchain.probe_container_runtime(str(docker))

    assert {probe.name: probe.version for probe in probes} == {
        "docker-client": "29.6.2",
        "docker-server": "29.6.2",
        "docker-compose": "5.3.1",
    }


@pytest.mark.parametrize(
    ("client", "server", "compose", "message"),
    [
        ("23.0.6", "29.6.2", "5.3.1", "Docker client must be >=24.0.0"),
        ("29.6.2", "23.0.6", "5.3.1", "Docker server must be >=24.0.0"),
        ("29.6.2", "29.6.2", "2.23.9", "Docker Compose must be >=2.24.0"),
    ],
)
def test_container_runtime_probe_rejects_unsupported_versions(
    tmp_path: Path,
    client: str,
    server: str,
    compose: str,
    message: str,
) -> None:
    docker = _write_docker_executable(
        tmp_path / "docker",
        client=client,
        server=server,
        compose=compose,
    )
    with pytest.raises(check_toolchain.ToolchainError, match=re.escape(message)):
        check_toolchain.probe_container_runtime(str(docker))


@pytest.mark.parametrize("value", ["29", "29.6", "unknown", "29.6.x"])
def test_container_versions_must_be_unambiguous_numeric_values(value: str) -> None:
    with pytest.raises(check_toolchain.ToolchainError, match="non-numeric"):
        check_toolchain.parse_numeric_version(value, "Docker")


@pytest.mark.parametrize(
    ("relative", "old", "new", "message"),
    [
        (".python-version", "3.14.7", "3.14.6", "pin mismatch"),
        ("pyproject.toml", "requires-python", "requires_python", "constrain Python"),
        (
            "pyproject.toml",
            'required-version = "==0.12.3"',
            'required-version = "==0.12.2"',
            "require uv ==0.12.3",
        ),
        ("uv.lock", "requires-python", "requires_python", "uv.lock"),
        ("package.json", "pnpm@11.21.0", "pnpm@11.20.0", "packageManager"),
        ("package.json", '"pnpm": "11.21.0"', '"pnpm": "11.20.0"', "engine"),
        ("pnpm-lock.yaml", "lockfileVersion", "lockfile_version", "lockfileVersion"),
    ],
)
def test_repository_pin_drift_fails_closed(
    tmp_path: Path,
    relative: str,
    old: str,
    new: str,
    message: str,
) -> None:
    _copy_toolchain_surface(tmp_path)
    path = tmp_path / relative
    original = path.read_text(encoding="utf-8")
    assert old in original
    path.write_text(original.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(check_toolchain.ToolchainError, match=message):
        check_toolchain.validate_repository_pins(tmp_path)


def test_missing_and_malformed_pin_files_fail_closed(tmp_path: Path) -> None:
    _copy_toolchain_surface(tmp_path)
    (tmp_path / ".node-version").unlink()
    with pytest.raises(check_toolchain.ToolchainError, match="missing regular"):
        check_toolchain.validate_repository_pins(tmp_path)

    _copy_toolchain_surface(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[", encoding="utf-8")
    with pytest.raises(check_toolchain.ToolchainError, match="valid TOML"):
        check_toolchain.validate_repository_pins(tmp_path)

    _copy_toolchain_surface(tmp_path)
    (tmp_path / "package.json").write_text("[", encoding="utf-8")
    with pytest.raises(check_toolchain.ToolchainError, match="valid JSON"):
        check_toolchain.validate_repository_pins(tmp_path)


def test_toolchain_cli_reports_success_and_safe_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    python = _write_executable(binaries / "python", "Python 3.14.7")
    node = _write_executable(binaries / "node", "v24.19.0")
    uv = _write_executable(binaries / "uv", "uv 0.12.3")
    pnpm = _write_executable(binaries / "pnpm", "11.21.0")

    assert (
        check_toolchain.main(
            [
                "--root",
                str(REPOSITORY_ROOT),
                "--python",
                str(python),
                "--node",
                str(node),
                "--uv",
                str(uv),
                "--pnpm",
                str(pnpm),
            ]
        )
        == 0
    )
    assert "TOOLCHAIN OK" in capsys.readouterr().out

    assert check_toolchain.main(["--root", str(tmp_path / "missing")]) == 1
    assert "TOOLCHAIN ERROR" in capsys.readouterr().err


def test_boundary_scan_requires_canonical_owned_roots_without_python_scaffolding(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="packages must be a real directory"):
        check_boundaries.find_boundary_violations(tmp_path)

    _write_domain_ownership(tmp_path)

    assert check_boundaries.find_boundary_violations(tmp_path) == ()
    assert not tuple((tmp_path / "packages").rglob("*.py"))


def test_boundary_scan_rejects_missing_or_renamed_domain_roots(
    tmp_path: Path,
) -> None:
    _write_domain_ownership(tmp_path)
    shutil.rmtree(tmp_path / "packages" / "flux")
    with pytest.raises(RuntimeError, match="missing flux"):
        check_boundaries.find_boundary_violations(tmp_path)

    _write_domain_ownership(tmp_path)
    (tmp_path / "packages" / "flux").rename(tmp_path / "packages" / "estimation")
    with pytest.raises(RuntimeError, match="missing flux; unexpected estimation"):
        check_boundaries.find_boundary_violations(tmp_path)


def test_boundary_scan_requires_substantive_regular_ownership_docs(
    tmp_path: Path,
) -> None:
    _write_domain_ownership(tmp_path)
    ownership = tmp_path / "packages" / "retrieval" / "OWNERSHIP.md"
    ownership.write_text("# Retrieval ownership\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="substantive ownership text"):
        check_boundaries.find_boundary_violations(tmp_path)

    ownership.unlink()
    with pytest.raises(
        RuntimeError,
        match=re.escape("OWNERSHIP.md must be a regular file"),
    ):
        check_boundaries.find_boundary_violations(tmp_path)


def test_boundary_scan_allows_domain_and_scientific_dependencies(
    tmp_path: Path,
) -> None:
    _write_domain_module(
        tmp_path,
        "from .services import DomainService\n"
        "import numpy as np\n"
        "import rasterio\n"
        "import torch\n",
    )

    assert check_boundaries.find_boundary_violations(tmp_path) == ()


def test_boundary_scan_rejects_application_transport_and_cloud_imports(
    tmp_path: Path,
) -> None:
    _write_domain_module(
        tmp_path,
        "from services.api import app\n"
        "import fastapi\n"
        "import httpx\n"
        "from cloud.runtime import state\n"
        "from google.cloud import storage\n",
    )

    violations = check_boundaries.find_boundary_violations(tmp_path)

    assert [violation.module for violation in violations] == [
        "services.api",
        "fastapi",
        "httpx",
        "cloud.runtime",
        "google.cloud",
    ]
    assert all(
        violation.path == "packages/retrieval/module.py" for violation in violations
    )


def test_boundary_scan_rejects_stdlib_transport_process_and_persistence(
    tmp_path: Path,
) -> None:
    _write_domain_module(
        tmp_path,
        "import socket\n"
        "from http import client\n"
        "from urllib import request\n"
        "import subprocess\n"
        "from asyncio.subprocess import Process\n"
        "import sqlite3\n",
    )

    violations = check_boundaries.find_boundary_violations(tmp_path)

    assert [violation.module for violation in violations] == [
        "socket",
        "http.client",
        "urllib",
        "subprocess",
        "asyncio.subprocess",
        "sqlite3",
    ]


def test_boundary_scan_rejects_literal_and_unverifiable_dynamic_imports(
    tmp_path: Path,
) -> None:
    _write_domain_module(
        tmp_path,
        "import importlib as loader\n"
        "from importlib import import_module as load\n"
        "loader.import_module('workers.acquisition')\n"
        "load('minio')\n"
        "load(target)\n"
        "load(42)\n"
        "load('.web', 'apps')\n"
        "__import__('apps.web')\n",
    )

    violations = check_boundaries.find_boundary_violations(tmp_path)

    assert [violation.module for violation in violations] == [
        "workers.acquisition",
        "minio",
        "<dynamic>",
        "<dynamic>",
        "<dynamic>",
        "apps.web",
    ]


def test_boundary_scan_rejects_builtins_import_aliases_and_dynamic_code(
    tmp_path: Path,
) -> None:
    _write_domain_module(
        tmp_path,
        "import builtins as b\n"
        "from builtins import __import__ as load\n"
        "from builtins import eval as evaluate\n"
        "loader = b.__import__\n"
        "runner = b.exec\n"
        "b.__import__('services.api')\n"
        "load('socket')\n"
        "loader('workers.acquisition')\n"
        "exec('import fastapi')\n"
        "evaluate('1 + 1')\n"
        "runner('import httpx')\n"
        "b.compile('1', '<domain>', 'eval')\n",
    )

    violations = check_boundaries.find_boundary_violations(tmp_path)

    assert [violation.module for violation in violations] == [
        "services.api",
        "socket",
        "workers.acquisition",
        "<dynamic-code>",
        "<dynamic-code>",
        "<dynamic-code>",
        "<dynamic-code>",
    ]


def test_unparseable_domain_source_is_a_boundary_failure(tmp_path: Path) -> None:
    _write_domain_module(tmp_path, "if:\n")

    violations = check_boundaries.find_boundary_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].category == "boundary analysis failure"


def test_boundary_scan_rejects_symlinked_domain_source(tmp_path: Path) -> None:
    _write_domain_ownership(tmp_path)
    target = tmp_path / "outside.py"
    target.write_text("import fastapi\n", encoding="utf-8")
    module = tmp_path / "packages" / "retrieval" / "module.py"
    module.symlink_to(target)

    violations = check_boundaries.find_boundary_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].category == "repository trust boundary"


def test_boundary_scan_rejects_symlinked_domain_directory(tmp_path: Path) -> None:
    _write_domain_ownership(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "module.py").write_text("import fastapi\n", encoding="utf-8")
    packages = tmp_path / "packages"
    shutil.rmtree(packages / "retrieval")
    (packages / "retrieval").symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="retrieval must be a real directory"):
        check_boundaries.find_boundary_violations(tmp_path)


def test_boundary_cli_reports_pass_violation_and_invalid_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_domain_ownership(tmp_path)
    assert check_boundaries.main(["--root", str(tmp_path)]) == 0
    assert "BOUNDARY OK" in capsys.readouterr().out

    violation = _write_domain_module(tmp_path, "import fastapi\n")
    assert check_boundaries.main(["--root", str(tmp_path)]) == 1
    failure = capsys.readouterr().err
    assert "BND001" in failure
    assert violation.relative_to(tmp_path).as_posix() in failure

    assert check_boundaries.main(["--root", str(tmp_path / "missing")]) == 1
    assert "BOUNDARY ERROR" in capsys.readouterr().err


def test_packages_path_must_be_a_real_directory(tmp_path: Path) -> None:
    (tmp_path / "packages").write_text("not a directory", encoding="utf-8")
    with pytest.raises(RuntimeError, match="real directory"):
        check_boundaries.find_boundary_violations(tmp_path)


def test_broken_packages_symlink_is_not_treated_as_absent(tmp_path: Path) -> None:
    (tmp_path / "packages").symlink_to(tmp_path / "missing")
    with pytest.raises(RuntimeError, match="real directory"):
        check_boundaries.find_boundary_violations(tmp_path)


def test_tier0_evidence_policy_allows_only_typed_command_and_ci_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "README.md").write_text("evidence policy\n", encoding="utf-8")
    (evidence / "dependency-audit.json").write_text("{}\n", encoding="utf-8")
    for filename, kind in check_boundaries.TIER0_EVIDENCE_KINDS.items():
        path = tmp_path / filename
        path.write_text(
            json.dumps(_tier0_evidence_payload(kind)) + "\n",
            encoding="utf-8",
        )

    assert check_boundaries.find_tier0_evidence_violations(tmp_path) == ()
    assert (
        check_boundaries.main(["--root", str(tmp_path), "--validate-tier0-evidence"])
        == 0
    )
    assert (
        "no domain metric artifacts are published at Tier 0" in capsys.readouterr().out
    )


def test_tier0_evidence_policy_rejects_domain_or_mistyped_artifacts(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "README.md").write_text("evidence policy\n", encoding="utf-8")
    (evidence / "dependency-audit.json").write_text("{}\n", encoding="utf-8")
    (evidence / "domain-metric.json").write_text(
        '{"accuracy": 0.99}\n', encoding="utf-8"
    )
    ci_path = tmp_path / "evidence" / "tier0-ci-run.json"
    invalid_ci = _tier0_evidence_payload("domain-evaluation")
    ci_path.write_text(json.dumps(invalid_ci) + "\n", encoding="utf-8")

    violations = check_boundaries.find_tier0_evidence_violations(tmp_path)

    assert [violation.path for violation in violations] == [
        "evidence/domain-metric.json",
        "evidence/tier0-ci-run.json",
    ]
    assert "real domain evaluation runner" in violations[0].detail
    assert "kind must be" in violations[1].detail


def test_current_repository_satisfies_domain_boundaries() -> None:
    assert check_boundaries.find_boundary_violations(REPOSITORY_ROOT) == ()


def test_makefile_exposes_the_full_gnu_make_381_command_contract() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in REQUIRED_TARGETS:
        encoded = target.replace(":", r"\:")
        assert re.search(rf"^{re.escape(encoded)}\s*:", makefile, re.MULTILINE), target

    unsupported_features = (".ONESHELL", "$(file ", "&:")
    assert not any(feature in makefile for feature in unsupported_features)
    assert "scripts/devctl.py preflight" in makefile
    assert "scripts/devctl.py up" in makefile
    assert "scripts/devctl.py health" in makefile
    assert "scripts/devctl.py down" in makefile
    assert "scripts/dev_secrets.py ensure" in makefile
    assert "scripts/init_object_store.py" in makefile
    assert "cleanup_status=$$?" in makefile
    assert "object-store initialization status=$$status" in makefile
    assert "scripts/devctl.py down || true" not in makefile
    assert "|| true" not in makefile
    for variable in ("UV_BIN", "PNPM_BIN", "DOCKER_BIN", "SYFT_BIN"):
        assert re.search(rf"^override {variable} :=", makefile, re.MULTILINE)
        assert not re.search(rf"^{variable} \?=", makefile, re.MULTILINE)
    assert "REQUESTED_PLAYWRIGHT_BROWSERS_PATH" in makefile
    assert "PLAYWRIGHT_BROWSERS_PATH must remain at" in makefile
    for tool in ("uv", "Node", "pnpm", "Docker"):
        assert f"lifecycle {tool} provenance differs" in makefile
    assert "--require-containers" in makefile
    assert "scripts/dependency_audit.py" in makefile
    assert "--offline" in makefile
    assert "playwright install chromium" in makefile
    assert not re.search(r"playwright install[^\n]*(?:firefox|webkit)", makefile)
    assert "scripts/generate_release_manifest.py" in makefile
    assert "--verify-reproducible" in makefile
    assert "pull catalog" in makefile
    assert "_secure-dev-root: _reject-control-environment" in makefile
    assert '"$(DEV_ROOT)/tmp"' in makefile
    assert '@mkdir -p "$(DEV_ROOT)/tmp"' not in makefile
    assert "--validate-tier0-evidence" in makefile
    release_gate = re.search(
        r"^release-check:\s*(?P<prerequisites>[^\n]+)", makefile, re.MULTILINE
    )
    assert release_gate is not None
    assert "sbom" in release_gate.group("prerequisites").split()

    phony_surface = _make_phony_surface(makefile)
    assert "_force-dev-command" in phony_surface
    for target in ("dev:preflight", "dev:up", "dev:health", "dev:down"):
        assert target.replace(":", r"\:") in phony_surface
        encoded = re.escape(target.replace(":", r"\:"))
        assert re.search(
            rf"^{encoded}\s*:[^\n]*\b_force-dev-command\b",
            makefile,
            re.MULTILINE,
        )


def test_makefile_isolates_tool_configuration_and_scopes_synthetic_reset() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    assert 'HOME="$(TOOL_HOME)"' in makefile
    assert 'DOCKER_CONFIG="$(DOCKER_CONFIG_ROOT)"' in makefile
    assert 'DOCKER_HOST="$(DOCKER_SOCKET_ENDPOINT)"' in makefile
    assert "DOCKER_SOCKET_ENDPOINT := unix:///var/run/docker.sock" in makefile
    assert "TIER0_CATALOG_VOLUME := $(PROJECT_NAME)_catalog_data" in makefile
    assert "TIER0_OBJECT_VOLUME := $(PROJECT_NAME)_object_data" in makefile
    assert "TIER0_SYNTHETIC_RESET=1" in makefile
    assert 'volume rm "$$volume"' in makefile
    assert "docker volume prune" not in makefile
    for directory in (
        "TOOL_HOME",
        "XDG_CONFIG_ROOT",
        "XDG_DATA_ROOT",
        "XDG_STATE_ROOT",
        "DOCKER_CONFIG_ROOT",
    ):
        assert f'"$({directory})"' in makefile
    for variable in (
        "DOCKER_HOST",
        "COMPOSE_*",
        "SYFT_*",
        "PYTEST_ADDOPTS",
        "COVERAGE_*",
        "NODE_OPTIONS",
        "UV_*",
        "BUILDKIT_*",
    ):
        assert variable in makefile


def test_dev_targets_remain_phony_when_sentinel_files_exist(tmp_path: Path) -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    phony_surface = _make_phony_surface(makefile)
    targets = ("dev:preflight", "dev:up", "dev:health", "dev:down")
    definitions: list[str] = []
    for target in targets:
        (tmp_path / target).touch()
        escaped = target.replace(":", r"\:")
        definitions.append(
            f"{escaped}: _force-dev-command\n\t@printf '%s\\n' '{target}'"
        )
    contract = tmp_path / "Makefile"
    contract.write_text(
        phony_surface + "\n" + "\n".join(definitions) + "\n",
        encoding="utf-8",
    )
    make = shutil.which("make")
    assert make is not None
    completed = subprocess.run(  # noqa: S603 -- resolved GNU Make, fixed arguments
        [str(Path(make).resolve()), "--no-print-directory", *targets],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == list(targets)


@pytest.mark.parametrize("initial_state", ["absent", "mode-0755"])
def test_make_secures_development_cache_before_use(
    tmp_path: Path,
    initial_state: str,
) -> None:
    development_root = tmp_path / ".dev"
    if initial_state == "mode-0755":
        development_root.mkdir(mode=0o755)
        development_root.chmod(0o755)
    cache_root = development_root / "cache"
    directories = (
        development_root,
        development_root / "tmp",
        cache_root,
        cache_root / "uv",
        cache_root / "python",
        cache_root / "pnpm-store",
        cache_root / "home",
        cache_root / "xdg-config",
        cache_root / "xdg-data",
        cache_root / "xdg-state",
        cache_root / "docker-config",
        cache_root / "playwright",
        cache_root / "xdg",
        cache_root / "npm",
    )
    make = shutil.which("make")
    assert make is not None
    completed = subprocess.run(  # noqa: S603 -- resolved GNU Make, fixed arguments
        [
            str(Path(make).resolve()),
            "--no-print-directory",
            "-f",
            str(REPOSITORY_ROOT / "Makefile"),
            "_secure-dev-root",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        env=_make_test_environment(
            {
                "UV_CACHE_DIR": str(cache_root / "uv"),
                "UV_PYTHON_INSTALL_DIR": str(cache_root / "python"),
                "PLAYWRIGHT_BROWSERS_PATH": str(cache_root / "playwright"),
                "COMPOSE_PROJECT_NAME": "gatewaygs-ai-4-earth-hackathon",
                "XDG_CACHE_HOME": str(cache_root / "xdg"),
                "npm_config_cache": str(cache_root / "npm"),
            }
        ),
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    for directory in directories:
        assert directory.is_dir()
        assert not directory.is_symlink()
        assert stat.S_IMODE(directory.stat().st_mode) == SECURE_DIRECTORY_MODE


def test_make_refuses_playwright_cache_outside_repository_dev(
    tmp_path: Path,
) -> None:
    development_root = tmp_path / ".dev"
    outside = tmp_path / "outside-playwright"
    outside.mkdir(mode=0o755)
    outside.chmod(0o755)
    make = shutil.which("make")
    assert make is not None
    completed = subprocess.run(  # noqa: S603 -- resolved GNU Make, fixed arguments
        [
            str(Path(make).resolve()),
            "--no-print-directory",
            "-f",
            str(REPOSITORY_ROOT / "Makefile"),
            "_secure-dev-root",
            f"PLAYWRIGHT_BROWSERS_PATH={outside}",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        env=_make_test_environment(),
        text=True,
    )
    assert completed.returncode != 0
    assert "PLAYWRIGHT_BROWSERS_PATH must remain at" in completed.stderr
    assert not development_root.exists()
    assert stat.S_IMODE(outside.stat().st_mode) == WORLD_READABLE_DIRECTORY_MODE


def test_make_tool_environment_ignores_ambient_home_and_docker_config(
    tmp_path: Path,
) -> None:
    development_root = tmp_path / ".dev"
    cache_root = development_root / "cache"
    ambient_home = tmp_path / "ambient-home"
    ambient_docker = ambient_home / ".docker"
    ambient_docker.mkdir(parents=True)
    (ambient_docker / "config.json").write_text(
        '{"currentContext":"foreign"}\n', encoding="utf-8"
    )
    contract = tmp_path / "ToolEnvironment.mk"
    contract.write_text(
        f"include {REPOSITORY_ROOT / 'Makefile'}\n"
        "print-tool-environment:\n"
        "\t@$(TOOL_ENV) env\n",
        encoding="utf-8",
    )
    make = shutil.which("make")
    assert make is not None
    completed = subprocess.run(  # noqa: S603 -- resolved GNU Make, fixed arguments
        [
            str(Path(make).resolve()),
            "--no-print-directory",
            "-f",
            str(contract),
            "print-tool-environment",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        env=_make_test_environment(
            {
                "HOME": str(ambient_home),
                "DOCKER_CONFIG": str(ambient_docker),
                "XDG_CONFIG_HOME": str(tmp_path / "ambient-xdg"),
            }
        ),
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    observed = dict(
        line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
    )
    assert observed["HOME"] == str(cache_root / "home")
    assert observed["DOCKER_CONFIG"] == str(cache_root / "docker-config")
    assert observed["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert observed["XDG_CONFIG_HOME"] == str(cache_root / "xdg-config")
    assert str(ambient_home) not in {
        observed["HOME"],
        observed["DOCKER_CONFIG"],
        observed["XDG_CONFIG_HOME"],
    }


def test_tier0_state_reset_previews_refuses_and_removes_only_exact_volumes(
    tmp_path: Path,
) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    _write_fake_reset_docker(binaries / "docker")
    make = shutil.which("make")
    assert make is not None
    project = "gatewaygs-ai-4-earth-hackathon"
    volumes = [f"{project}_catalog_data", f"{project}_object_data"]
    compose_prefix = [
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(tmp_path / "ports.env"),
        "--file",
        str(tmp_path / "compose.yaml"),
    ]
    expected_preview = [
        ["volume", "ls", "--quiet", "--filter", f"name=^{volume}$"]
        for volume in volumes
    ] + [[*compose_prefix, "ps", "--all", "--quiet"]]

    def invoke(
        log: Path,
        *,
        authorize: bool,
        volume_mode: str = "exact",
        containers_present: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        arguments = [
            str(Path(make).resolve()),
            "--no-print-directory",
            "-f",
            str(REPOSITORY_ROOT / "Makefile"),
            "reset-tier0-state",
        ]
        if authorize:
            arguments.append("TIER0_SYNTHETIC_RESET=1")
        return subprocess.run(  # noqa: S603 -- resolved GNU Make, fixed arguments
            arguments,
            cwd=tmp_path,
            check=False,
            capture_output=True,
            env=_make_test_environment(
                {
                    "PATH": os.pathsep.join((str(binaries), "/usr/bin", "/bin")),
                    "FAKE_LOG": str(log),
                    "FAKE_VOLUME_MODE": volume_mode,
                    "FAKE_CONTAINERS": ("present" if containers_present else "absent"),
                }
            ),
            text=True,
        )

    refused_log = tmp_path / "refused.log"
    refused = invoke(refused_log, authorize=False)
    assert refused.returncode != 0
    assert "RESET PREVIEW" in refused.stdout
    assert "synthetic Tier 0 data loss" in refused.stderr
    assert [json.loads(line) for line in refused_log.read_text().splitlines()] == (
        expected_preview
    )

    reset_log = tmp_path / "reset.log"
    reset = invoke(reset_log, authorize=True)
    assert reset.returncode == 0, reset.stderr
    assert "only named synthetic Tier 0 volumes were removed" in reset.stdout
    assert [json.loads(line) for line in reset_log.read_text().splitlines()] == [
        *expected_preview,
        *[["volume", "rm", volume] for volume in volumes],
    ]

    containers_log = tmp_path / "containers.log"
    containers = invoke(
        containers_log,
        authorize=True,
        containers_present=True,
    )
    assert containers.returncode != 0
    assert "owned by a running checkout" in containers.stderr
    assert "make dev:down in the owning checkout" in containers.stderr
    assert [json.loads(line) for line in containers_log.read_text().splitlines()] == (
        expected_preview
    )

    foreign_log = tmp_path / "foreign.log"
    foreign = invoke(foreign_log, authorize=True, volume_mode="foreign")
    assert foreign.returncode != 0
    assert "inexact name" in foreign.stderr
    foreign_calls = [json.loads(line) for line in foreign_log.read_text().splitlines()]
    assert foreign_calls == [expected_preview[0]]
    assert all("down" not in call and "rm" not in call for call in foreign_calls)


def test_make_refuses_symlinked_dev_tmp_before_writing_outside(
    tmp_path: Path,
) -> None:
    development_root = tmp_path / ".dev"
    development_root.mkdir(mode=SECURE_DIRECTORY_MODE)
    cache_root = development_root / "cache"
    outside = tmp_path / "outside-tmp"
    outside.mkdir(mode=WORLD_READABLE_DIRECTORY_MODE)
    outside.chmod(WORLD_READABLE_DIRECTORY_MODE)
    (development_root / "tmp").symlink_to(outside, target_is_directory=True)
    make = shutil.which("make")
    assert make is not None
    completed = subprocess.run(  # noqa: S603 -- resolved GNU Make, fixed arguments
        [
            str(Path(make).resolve()),
            "--no-print-directory",
            "-f",
            str(REPOSITORY_ROOT / "Makefile"),
            "_secure-dev-root",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        env=_make_test_environment(),
        text=True,
    )
    assert completed.returncode != 0
    assert str(development_root / "tmp") in completed.stderr
    assert not cache_root.exists()
    assert stat.S_IMODE(outside.stat().st_mode) == WORLD_READABLE_DIRECTORY_MODE
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DOCKER_HOST", "tcp://attacker.invalid:2375"),
        ("COMPOSE_FILE", "/untrusted/foreign-compose.yaml"),
        ("SYFT_CONFIG", "/untrusted/foreign-syft.yaml"),
        ("SYFT_OUTPUT", "template=/untrusted/redirected"),
        ("PYTHONPATH", "/untrusted/injected-python"),
        ("PYTEST_ADDOPTS", "--no-cov"),
        ("COVERAGE_FILE", "/untrusted/redirected-coverage"),
        ("NODE_OPTIONS", "--require=/untrusted/injected-node.cjs"),
        ("LD_PRELOAD", "/untrusted/injected-loader.so"),
        ("DYLD_INSERT_LIBRARIES", "/untrusted/injected-loader.dylib"),
        ("BASH_ENV", "/untrusted/injected-bash"),
        ("ENV", "/untrusted/injected-shell"),
        ("NODE_BINARY", "/untrusted/fake-node"),
        ("npm_config_registry", "https://attacker.invalid"),
        ("UV_NO_SYNC", "injected-control-value"),
        ("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "injected-control-value"),
        ("DOCKER_DEFAULT_PLATFORM", "linux/386"),
        ("BUILDKIT_PROGRESS", "plain"),
        ("XDG_CONFIG_HOME", "/untrusted/foreign-config"),
    ],
)
def test_make_rejects_ambient_control_environment_before_dev_writes(
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    development_root = tmp_path / ".dev"
    make = shutil.which("make")
    assert make is not None
    completed = subprocess.run(  # noqa: S603 -- resolved GNU Make, fixed arguments
        [
            str(Path(make).resolve()),
            "--no-print-directory",
            "-f",
            str(REPOSITORY_ROOT / "Makefile"),
            "_secure-dev-root",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        env=_make_test_environment({name: value}),
        text=True,
    )
    assert completed.returncode != 0
    assert name in completed.stderr
    assert value not in completed.stderr
    assert not development_root.exists()


def test_minio_build_context_is_default_deny() -> None:
    patterns = [
        line
        for raw_line in (REPOSITORY_ROOT / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]
    assert patterns == [
        "**",
        "!infra/",
        "!infra/minio/",
        "!infra/minio/Dockerfile",
    ]
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "context: ." in compose
    assert "dockerfile: infra/minio/Dockerfile" in compose
    assert "name: gatewaygs-ai-4-earth-hackathon_catalog_data" in compose
    assert "name: gatewaygs-ai-4-earth-hackathon_object_data" in compose


def test_e2e_policy_disallows_retries_and_uses_repo_scoped_profile() -> None:
    config = (REPOSITORY_ROOT / "apps/web/playwright.config.ts").read_text(
        encoding="utf-8"
    )
    fixtures = (REPOSITORY_ROOT / "apps/web/tests/fixtures.ts").read_text(
        encoding="utf-8"
    )
    global_setup = (REPOSITORY_ROOT / "apps/web/tests/global-setup.ts").read_text(
        encoding="utf-8"
    )
    assert re.search(r"\bretries:\s*0\s*,", config)
    assert not re.search(r"\bretries:\s*process\.env", config)
    assert re.search(r"\bforbidOnly:\s*true\s*,", config)
    assert "Boolean(process.env.CI)" not in config
    assert 'globalSetup: "./tests/global-setup.ts"' in config
    assert 'path.join(developmentRoot, "pw-profile")' in fixtures
    assert "chromium.launchPersistentContext(workerProfile" in fixtures
    assert "must be a real directory" in fixtures
    assert 'path.join(repositoryRoot, ".venv", "bin", "python")' in global_setup
    assert 'execFileAsync(python, [devctl, "health"]' in global_setup
    assert 'includes("HEALTH OK;")' in global_setup


def test_ci_uses_exact_tools_frozen_locks_and_scoped_runtime() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(
        encoding="utf-8"
    )
    assert "python-version: 3.14.7" in workflow
    assert "node-version: 24.19.0" in workflow
    assert "version: 0.12.3" in workflow
    assert "version: 11.21.0" in workflow
    assert "syft-version: v1.49.0" in workflow
    assert "anchore/sbom-action/download-syft@" in workflow
    assert "make bootstrap" in workflow
    assert "make verify-all" in workflow
    reset_command = "make reset-tier0-state TIER0_SYNTHETIC_RESET=1"
    assert reset_command in workflow
    assert workflow.index(reset_command) < workflow.index("make bootstrap")
    assert "make dev:down || true" not in workflow
    assert "--project-name gatewaygs-ai-4-earth-hackathon" in workflow
    assert "PLAYWRIGHT_BROWSERS_PATH" in workflow
    assert "playwright install --with-deps chromium" in workflow
    assert not re.search(r"playwright install[^\n]*(?:firefox|webkit)", workflow)
    assert "restore-keys:" not in workflow

    action_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]
    assert action_lines
    assert all(re.search(r"@[0-9a-f]{40}(?:\s|$)", line) for line in action_lines)


def test_command_surfaces_never_use_cross_repository_process_sweeps() -> None:
    surfaces = "\n".join(
        (REPOSITORY_ROOT / relative).read_text(encoding="utf-8")
        for relative in ("Makefile", ".github/workflows/ci.yml")
    )
    prohibited = (
        "pkill ",
        "killall ",
        "docker system prune",
        "docker kill $(docker ps -q)",
    )
    assert not any(command in surfaces for command in prohibited)


def test_release_tool_environment_drops_ambient_execution_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = {
        "DOCKER_HOST": "tcp://attacker.invalid:2375",
        "DOCKER_CONTEXT": "foreign",
        "DOCKER_CONFIG": "/untrusted/docker-config",
        "COMPOSE_FILE": "/untrusted/foreign-compose.yaml",
        "SYFT_CONFIG": "/untrusted/foreign-syft.yaml",
        "SYFT_OUTPUT": "template=/untrusted/redirected",
        "PYTHONPATH": "/untrusted/injected-python",
        "NODE_OPTIONS": "--require=/untrusted/injected-node.cjs",
        "UV_NO_SYNC": "1",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        "BUILDKIT_PROGRESS": "plain",
    }
    for name, value in hostile.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/untrusted/safe-home")

    base_environment = generate_release_manifest._base_tool_environment()
    syft_environment = generate_release_manifest._syft_environment()

    stripped = hostile.keys() - {"DOCKER_HOST"}
    assert not stripped & base_environment.keys()
    assert not stripped & syft_environment.keys()
    assert (
        base_environment["DOCKER_HOST"]
        == generate_release_manifest.DOCKER_SOCKET_ENDPOINT
    )
    assert (
        syft_environment["DOCKER_HOST"]
        == generate_release_manifest.DOCKER_SOCKET_ENDPOINT
    )
    assert base_environment["PATH"] == "/usr/bin:/bin"
    assert base_environment["HOME"] == "/untrusted/safe-home"
    expected_tmp = str(REPOSITORY_ROOT / ".dev" / "tmp")
    assert base_environment["TMPDIR"] == expected_tmp
    assert base_environment["TEMP"] == expected_tmp
    assert base_environment["TMP"] == expected_tmp
    assert base_environment["LC_ALL"] == "C"
    assert base_environment["TZ"] == "UTC"
    assert syft_environment["SYFT_CHECK_FOR_APP_UPDATE"] == "false"
    assert syft_environment["SYFT_PARALLELISM"] == "1"


def test_release_scans_force_empty_syft_config_and_clean_tool_environments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application_payload = _cyclonedx_payload("application-lock")
    metadata = application_payload["metadata"]
    assert isinstance(metadata, dict)
    metadata["component"] = {
        "type": "file",
        "name": generate_release_manifest.PROJECT_NAME,
        "version": generate_release_manifest.PROJECT_VERSION,
        "bom-ref": "volatile-application-source",
    }
    image_payload = _cyclonedx_payload("image")
    docker_payload = {
        "Id": "sha256:" + ("a" * 64),
        "Architecture": "amd64",
        "Os": "linux",
        "RepoDigests": [],
        "Config": {"Labels": {}},
    }
    calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def fake_run_command(
        executable: Path,
        argv: tuple[str, ...],
        label: str,
        *,
        environment: dict[str, str] | None = None,
    ) -> str:
        del executable
        calls.append((argv, environment))
        if label == "application lock SBOM scan":
            return json.dumps(application_payload)
        if label == "test image SBOM scan":
            return json.dumps(image_payload)
        if label == "test image inspection":
            return json.dumps(docker_payload)
        raise AssertionError(label)

    monkeypatch.setattr(generate_release_manifest, "_run_command", fake_run_command)
    generate_release_manifest._scan_application_locks(tmp_path, Path("/syft"))
    generate_release_manifest._scan_image(Path("/syft"), "image:test", "test")
    generate_release_manifest._image_descriptor(Path("/docker"), "image:test", "test")

    scan_calls = calls[:2]
    assert all(argv[:3] == ("scan", "--config", os.devnull) for argv, _ in scan_calls)
    assert all(environment is not None for _, environment in calls)
    assert all(
        environment.get("DOCKER_HOST")
        == generate_release_manifest.DOCKER_SOCKET_ENDPOINT
        for _, environment in calls
        if environment is not None
    )


def test_cyclonedx_normalization_removes_only_volatile_identity() -> None:
    first = _cyclonedx_payload("locked-dependency")
    second = _cyclonedx_payload("locked-dependency")
    first["serialNumber"] = "urn:uuid:first"
    second["serialNumber"] = "urn:uuid:second"
    first_metadata = first["metadata"]
    second_metadata = second["metadata"]
    assert isinstance(first_metadata, dict)
    assert isinstance(second_metadata, dict)
    first_metadata["timestamp"] = "first"
    second_metadata["timestamp"] = "second"

    first_bom = generate_release_manifest.normalize_cyclonedx(json.dumps(first))
    second_bom = generate_release_manifest.normalize_cyclonedx(json.dumps(second))

    assert first_bom == second_bom
    normalized = json.loads(first_bom.data)
    assert "serialNumber" not in normalized
    assert "timestamp" not in normalized["metadata"]
    assert first_bom.component_count == 1


def test_cyclonedx_normalization_is_independent_of_checkout_path(
    tmp_path: Path,
) -> None:
    normalized: list[generate_release_manifest.NormalizedBom] = []
    for name in ("first-checkout", "a-different-checkout-location"):
        root = tmp_path / name
        root.mkdir()
        payload = _cyclonedx_payload("locked-dependency")
        metadata = payload["metadata"]
        assert isinstance(metadata, dict)
        metadata["component"] = {
            "type": "file",
            "name": generate_release_manifest.PROJECT_NAME,
            "version": generate_release_manifest.PROJECT_VERSION,
            "bom-ref": f"volatile-source-reference-{name}",
        }
        reference = f"{root}/pnpm-lock.yaml"
        components = payload["components"]
        dependencies = payload["dependencies"]
        assert isinstance(components, list)
        assert isinstance(dependencies, list)
        components.append(
            {
                "type": "file",
                "name": reference,
                "bom-ref": reference,
            }
        )
        dependencies.append({"ref": reference, "dependsOn": []})
        normalized.append(
            generate_release_manifest.normalize_cyclonedx(
                json.dumps(payload),
                checkout_root=root,
            )
        )

    assert normalized[0] == normalized[1]
    document = json.loads(normalized[0].data)
    file_component = next(
        component for component in document["components"] if component["type"] == "file"
    )
    assert file_component["name"] == "pnpm-lock.yaml"
    assert file_component["bom-ref"] == "pnpm-lock.yaml"
    assert str(tmp_path) not in normalized[0].data.decode()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("specVersion", "1.6"), "specVersion drifted"),
        (("serialNumber", "not-a-uuid"), "serialNumber"),
        (("components", []), "no components"),
    ],
)
def test_cyclonedx_normalization_fails_on_schema_or_inventory_drift(
    mutation: tuple[str, object],
    message: str,
) -> None:
    payload = _cyclonedx_payload("dependency")
    payload[mutation[0]] = mutation[1]
    with pytest.raises(generate_release_manifest.ReleaseManifestError, match=message):
        generate_release_manifest.normalize_cyclonedx(json.dumps(payload))


def test_release_manifest_cli_is_reproducible_and_writes_bounded_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_release_surface(tmp_path)
    syft = _write_fake_syft(tmp_path / "syft")
    docker = _write_fake_release_docker(tmp_path / "docker")
    output = tmp_path / ".dev" / "release"

    result = generate_release_manifest.main(
        [
            "--root",
            str(tmp_path),
            "--output-dir",
            str(output),
            "--syft",
            str(syft),
            "--docker",
            str(docker),
            "--verify-reproducible",
        ]
    )

    assert result == 0
    assert "RELEASE MANIFEST OK" in capsys.readouterr().out
    assert {path.name for path in output.iterdir()} == (
        generate_release_manifest.EXPECTED_OUTPUTS
    )
    assert stat.S_IMODE((tmp_path / ".dev").stat().st_mode) == SECURE_DIRECTORY_MODE
    assert stat.S_IMODE(output.stat().st_mode) == SECURE_DIRECTORY_MODE
    manifest = json.loads((output / "release-manifest.json").read_text())
    assert manifest["status"] == "local-release-artifacts-not-production"
    assert manifest["command"] == "make sbom"
    assert manifest["seed"] is None
    assert "API and worker processes run from source" in manifest["scope"]
    assert len(manifest["inputs"]) == len(
        generate_release_manifest.RELEASE_INPUTS
    ) + len(generate_release_manifest.RELEASE_INPUT_DIRECTORIES)
    assert ".dockerignore" in {item["path"] for item in manifest["inputs"]}
    assert len(manifest["sboms"]) == EXPECTED_SBOM_COUNT
    assert manifest["artifacts"][0]["file_count"] == 1
    assert manifest["artifacts"][1]["platform"] == "linux/amd64"
    assert manifest["artifacts"][2]["platform"] == "linux/amd64"
    assert {artifact.get("reference") for artifact in manifest["artifacts"]} == {
        None,
        generate_release_manifest.MINIO_IMAGE,
        generate_release_manifest.POSTGIS_IMAGE,
    }
    assert "com.docker.compose.version" not in json.dumps(manifest)


def test_complete_release_bundle_is_independent_of_checkout_path(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    syft = _write_fake_syft(tools / "syft")
    docker = _write_fake_release_docker(tools / "docker")
    bundles: list[dict[str, bytes]] = []
    for name in ("checkout-a", "checkout-with-a-different-name"):
        root = tmp_path / name
        root.mkdir()
        _write_release_surface(root)
        bundles.append(generate_release_manifest.generate_bundle(root, syft, docker))

    assert bundles[0] == bundles[1]


def test_release_outputs_cannot_escape_dev_or_follow_symlinks(tmp_path: Path) -> None:
    bundle = dict.fromkeys(generate_release_manifest.EXPECTED_OUTPUTS, b"{}\n")
    with pytest.raises(
        generate_release_manifest.ReleaseManifestError,
        match=re.escape("below .dev"),
    ):
        generate_release_manifest._write_bundle(
            tmp_path,
            tmp_path / "outside",
            bundle,
        )

    redirect = tmp_path / ".dev" / "redirect"
    redirect.mkdir()
    output_link = tmp_path / ".dev" / "release"
    output_link.symlink_to(redirect, target_is_directory=True)
    with pytest.raises(
        generate_release_manifest.ReleaseManifestError,
        match="output directory must not be a symlink",
    ):
        generate_release_manifest._write_bundle(tmp_path, output_link, bundle)

    _write_release_surface(tmp_path)
    artifact = tmp_path / "apps" / "web" / "dist" / "linked.js"
    artifact.symlink_to(tmp_path / "package.json")
    with pytest.raises(
        generate_release_manifest.ReleaseManifestError,
        match="contains a symlink",
    ):
        generate_release_manifest._directory_descriptor(tmp_path, "apps/web/dist")


def test_release_output_recovers_its_own_interrupted_temporary_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / ".dev" / "release"
    output.mkdir(parents=True)
    stale = output / ".release-manifest.json.tmp"
    stale.write_bytes(b"interrupted")
    bundle = dict.fromkeys(generate_release_manifest.EXPECTED_OUTPUTS, b"{}\n")

    generate_release_manifest._write_bundle(tmp_path, output, bundle)

    assert not stale.exists()
    assert {path.name for path in output.iterdir()} == (
        generate_release_manifest.EXPECTED_OUTPUTS
    )


def test_release_reproducibility_comparison_fails_closed() -> None:
    first = dict.fromkeys(generate_release_manifest.EXPECTED_OUTPUTS, b"first")
    second = dict(first)
    second["release-manifest.json"] = b"second"
    with pytest.raises(
        generate_release_manifest.ReleaseManifestError,
        match=re.escape("release-manifest.json"),
    ):
        generate_release_manifest._require_reproducible(first, second)
