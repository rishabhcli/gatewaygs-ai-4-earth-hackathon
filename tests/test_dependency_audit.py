"""Adversarial tests for the offline Tier 0 dependency audit."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from scripts.dependency_audit import (
    EVIDENCE_COMMAND,
    REGISTER_END,
    REGISTER_START,
    audit,
    main,
    redact,
    semver_satisfies,
)

if TYPE_CHECKING:
    from collections.abc import Callable

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUDIT_INPUT_FILES = (
    ".dockerignore",
    ".node-version",
    ".python-version",
    "Makefile",
    "SUPPORT_MATRIX.md",
    "apps/web/index.html",
    "apps/web/package.json",
    "apps/web/playwright.config.ts",
    "apps/web/tsconfig.json",
    "apps/web/vite.config.ts",
    "compose.yaml",
    "docs/dependencies.md",
    "infra/minio/Dockerfile",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "scripts/check_boundaries.py",
    "scripts/check_toolchain.py",
    "scripts/dependency_audit.py",
    "scripts/devctl.py",
    "scripts/generate_release_manifest.py",
    "uv.lock",
)
AUDIT_INPUT_DIRECTORIES = (
    ".github/workflows",
    "apps/web/public",
    "apps/web/src",
    "apps/web/tests",
)
EXPECTED_REGISTER_ENTRY_COUNT = 56
EXPECTED_GITHUB_ACTION_COUNT = 7
EXPECTED_REDACTION_COUNT = 3


def _copy_audit_root(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    for relative in AUDIT_INPUT_FILES:
        source = REPOSITORY_ROOT / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for relative in AUDIT_INPUT_DIRECTORIES:
        shutil.copytree(REPOSITORY_ROOT / relative, root / relative)
    return root


def _finding_codes(root: Path) -> set[str]:
    return {finding.code for finding in audit(root).findings}


def _replace(path: Path, old: str, new: str) -> None:
    original = path.read_text(encoding="utf-8")
    assert old in original
    path.write_text(original.replace(old, new, 1), encoding="utf-8")


def _load_json(path: Path) -> dict[str, object]:
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return cast("dict[str, object]", parsed)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _edit_register(root: Path, edit: Callable[[list[dict[str, object]]], None]) -> None:
    path = root / "docs/dependencies.md"
    text = path.read_text(encoding="utf-8")
    body = text.split(REGISTER_START, 1)[1].split(REGISTER_END, 1)[0].strip()
    assert body.startswith("```json")
    assert body.endswith("```")
    parsed: object = json.loads(body[len("```json") : -len("```")])
    assert isinstance(parsed, dict)
    entries_raw = parsed.get("entries")
    assert isinstance(entries_raw, list)
    entries: list[dict[str, object]] = []
    for entry in entries_raw:
        assert isinstance(entry, dict)
        entries.append(cast("dict[str, object]", entry))
    edit(entries)
    parsed["entries"] = entries
    fenced = "```json\n" + json.dumps(parsed, indent=2, sort_keys=True) + "\n```"
    prefix = text.split(REGISTER_START, 1)[0]
    suffix = text.split(REGISTER_END, 1)[1]
    path.write_text(
        prefix + REGISTER_START + "\n" + fenced + "\n" + REGISTER_END + suffix,
        encoding="utf-8",
    )


def _entry(entries: list[dict[str, object]], entry_id: str) -> dict[str, object]:
    return next(entry for entry in entries if entry.get("id") == entry_id)


def test_repository_audit_passes_and_is_deterministic() -> None:
    report = audit(REPOSITORY_ROOT)

    assert report.passed, report.to_json()
    assert report.to_json() == audit(REPOSITORY_ROOT).to_json()
    evidence = report.as_dict()
    assert evidence["status"] == "pass"
    assert evidence["command"] == EVIDENCE_COMMAND
    assert evidence["seed"] is None
    assert evidence["network"] == {"mode": "offline-only", "used": False}
    assert str(REPOSITORY_ROOT) not in report.to_json()
    assert len(report.entries) == EXPECTED_REGISTER_ENTRY_COUNT
    direct = evidence["summary"]
    assert isinstance(direct, dict)
    direct_counts = direct["direct_dependencies"]
    assert isinstance(direct_counts, dict)
    assert direct_counts["github-action"] == EXPECTED_GITHUB_ACTION_COUNT
    registered_counts = direct["registered_entry_kinds"]
    assert isinstance(registered_counts, dict)
    assert registered_counts == {
        "container": 5,
        "github-action": 7,
        "npm": 19,
        "python": 14,
        "source": 1,
        "tool": 10,
    }


def test_cli_writes_identical_atomic_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _copy_audit_root(tmp_path)
    output = root / "evidence/custom.json"

    assert main(["--root", str(root), "--write-evidence", "--output", str(output)]) == 0
    first = output.read_text(encoding="utf-8")
    assert capsys.readouterr().out == first
    assert not output.with_suffix(".json.tmp").exists()

    assert main(["--root", str(root), "--write-evidence", "--output", str(output)]) == 0
    assert capsys.readouterr().out == first
    assert output.read_text(encoding="utf-8") == first


def test_evidence_hashes_every_policy_and_release_input() -> None:
    report = audit(REPOSITORY_ROOT)
    observed_paths = [path for path, _digest in report.input_hashes]
    expected = set(AUDIT_INPUT_FILES)
    for relative_directory in AUDIT_INPUT_DIRECTORIES:
        expected.update(
            path.relative_to(REPOSITORY_ROOT).as_posix()
            for path in (REPOSITORY_ROOT / relative_directory).rglob("*")
            if path.is_file()
        )

    assert set(observed_paths) == expected
    assert observed_paths == sorted(observed_paths)


def test_symlinked_release_input_directory_fails_closed(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    shutil.rmtree(root / "apps/web/public")
    (root / "apps/web/public").symlink_to(
        root / "apps/web/src", target_is_directory=True
    )

    assert "AUDIT_INPUT_MISSING" in _finding_codes(root)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            '"fastapi==0.141.1",',
            '"fastapi>=0.141.1",',
            "UNPINNED_DIRECT_DEPENDENCY",
        ),
        (
            '"fastapi==0.141.1",',
            '"example-package==1.0.0",\n  "fastapi==0.141.1",',
            "UNREGISTERED_DIRECT_DEPENDENCY",
        ),
    ],
)
def test_python_direct_dependency_failures(
    tmp_path: Path, old: str, new: str, expected: str
) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / "pyproject.toml", old, new)

    assert expected in _finding_codes(root)


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("^4.4.3", "UNPINNED_DIRECT_DEPENDENCY"),
        ("4.4.4", "REGISTER_VERSION_MISMATCH"),
    ],
)
def test_npm_pin_failures(tmp_path: Path, version: str, expected: str) -> None:
    root = _copy_audit_root(tmp_path)
    package_path = root / "apps/web/package.json"
    package = _load_json(package_path)
    dependencies = package["dependencies"]
    assert isinstance(dependencies, dict)
    dependencies["zod"] = version
    _write_json(package_path, package)

    assert expected in _finding_codes(root)


def test_unregistered_npm_dependency_fails(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    package_path = root / "apps/web/package.json"
    package = _load_json(package_path)
    dependencies = package["dependencies"]
    assert isinstance(dependencies, dict)
    dependencies["left-pad"] = "1.3.0"
    _write_json(package_path, package)

    assert "UNREGISTERED_DIRECT_DEPENDENCY" in _finding_codes(root)


def test_mutable_github_action_reference_fails(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(
        root / ".github/workflows/ci.yml",
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4",
        "actions/checkout@v4",
    )

    assert "UNPINNED_GITHUB_ACTION" in _finding_codes(root)


@pytest.mark.parametrize(
    "replacement",
    [
        "      uses : actions/checkout@v4",
        '      "uses" : "actions/checkout@v4"',
    ],
)
def test_alternate_yaml_action_key_cannot_bypass_pin_check(
    tmp_path: Path, replacement: str
) -> None:
    root = _copy_audit_root(tmp_path)
    workflow = root / ".github/workflows/ci.yml"
    original = (
        "        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4"
    )
    _replace(workflow, original, replacement)

    assert "UNPINNED_GITHUB_ACTION" in _finding_codes(root)


def test_flow_style_action_use_fails_closed(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    workflow = root / ".github/workflows/ci.yml"
    original = (
        "        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4"
    )
    _replace(workflow, original, "      - { uses: actions/checkout@v4 }")

    assert "AUDIT_INPUT_INVALID" in _finding_codes(root)


def test_local_composite_action_uses_are_audited(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    action = root / ".github/actions/example/action.yml"
    action.parent.mkdir(parents=True)
    action.write_text(
        "name: example\nruns:\n  using: composite\n  steps:\n"
        "    - uses: example/external@v1\n",
        encoding="utf-8",
    )

    assert "UNPINNED_GITHUB_ACTION" in _finding_codes(root)


def test_new_pinned_github_action_must_be_registered(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    workflow = root / ".github/workflows/ci.yml"
    workflow.write_text(
        workflow.read_text(encoding="utf-8")
        + (
            "\n      - uses: example/action@"
            "0123456789abcdef0123456789abcdef01234567 # v1\n"
        ),
        encoding="utf-8",
    )

    assert "UNREGISTERED_DIRECT_DEPENDENCY" in _finding_codes(root)


def test_new_workflow_action_must_be_registered(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    (root / ".github/workflows/nightly.yml").write_text(
        "jobs:\n  audit:\n    steps:\n"
        "      - uses: example/nightly@"
        "0123456789abcdef0123456789abcdef01234567 # v1\n",
        encoding="utf-8",
    )

    assert "UNREGISTERED_DIRECT_DEPENDENCY" in _finding_codes(root)


def test_github_action_register_reference_is_exact(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def drift_reference(entries: list[dict[str, object]]) -> None:
        target = _entry(entries, "github-action:actions-checkout")
        manifest = target["manifest"]
        assert isinstance(manifest, dict)
        manifest["reference"] = "actions/checkout@v4"

    _edit_register(root, drift_reference)
    assert "GITHUB_ACTION_REFERENCE_MISMATCH" in _finding_codes(root)


def test_github_action_release_annotation_is_audited(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(
        root / ".github/workflows/ci.yml",
        "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830 # v4.3.0",
        "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830 # v4.2.0",
    )

    assert "GITHUB_ACTION_RELEASE_LINE_MISMATCH" in _finding_codes(root)


def test_removed_github_action_register_entry_fails(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def remove_action(entries: list[dict[str, object]]) -> None:
        entries.remove(_entry(entries, "github-action:actions-setup-python"))

    _edit_register(root, remove_action)
    assert "UNREGISTERED_DIRECT_DEPENDENCY" in _finding_codes(root)


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    [
        (
            "compose.yaml",
            "postgis/postgis:16-3.5-alpine@sha256:",
            "postgis/postgis:16-3.5-alpine#sha256:",
        ),
        (
            "infra/minio/Dockerfile",
            "docker/dockerfile:1.18@sha256:",
            "docker/dockerfile:1.18#sha256:",
        ),
        (
            "infra/minio/Dockerfile",
            "golang:1.24.8-alpine3.22@sha256:",
            "golang:1.24.8-alpine3.22#sha256:",
        ),
    ],
)
def test_mutable_external_container_reference_fails(
    tmp_path: Path, relative: str, old: str, new: str
) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / relative, old, new)

    assert "MUTABLE_CONTAINER_REFERENCE" in _finding_codes(root)


@pytest.mark.parametrize(
    ("package_name", "version"),
    [("typescript", "7.0.2"), ("eslint", "11.0.0")],
)
def test_incompatible_typescript_eslint_tuple_fails(
    tmp_path: Path, package_name: str, version: str
) -> None:
    root = _copy_audit_root(tmp_path)
    package_path = root / "apps/web/package.json"
    package = _load_json(package_path)
    dependencies = package["devDependencies"]
    assert isinstance(dependencies, dict)
    dependencies[package_name] = version
    _write_json(package_path, package)

    assert "INCOMPATIBLE_TYPESCRIPT_ESLINT_PIN" in _finding_codes(root)


def test_eslint_and_official_config_major_must_match(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    package_path = root / "apps/web/package.json"
    package = _load_json(package_path)
    dependencies = package["devDependencies"]
    assert isinstance(dependencies, dict)
    dependencies["@eslint/js"] = "9.0.0"
    _write_json(package_path, package)

    assert "INCOMPATIBLE_ESLINT_JS_PIN" in _finding_codes(root)


def test_minio_can_never_be_production_approved(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def approve(entries: list[dict[str, object]]) -> None:
        _entry(entries, "container:minio-local")["production_approved"] = True

    _edit_register(root, approve)
    assert "MINIO_PRODUCTION_APPROVAL_FORBIDDEN" in _finding_codes(root)


def test_every_declared_tool_must_remain_registered(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def remove_docker(entries: list[dict[str, object]]) -> None:
        entries.remove(_entry(entries, "tool:docker-engine"))

    _edit_register(root, remove_docker)
    assert "UNREGISTERED_TOOL" in _finding_codes(root)


def test_syft_tool_must_remain_registered(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def remove_syft(entries: list[dict[str, object]]) -> None:
        entries.remove(_entry(entries, "tool:syft"))

    _edit_register(root, remove_syft)
    assert "UNREGISTERED_TOOL" in _finding_codes(root)


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    [
        (
            ".github/workflows/ci.yml",
            "syft-version: v1.49.0",
            "syft-version: v1.48.0",
        ),
        ("Makefile", "SYFT_VERSION := 1.49.0", "SYFT_VERSION := 1.48.0"),
        (
            "Makefile",
            "override SYFT_BIN := $(shell command -v syft 2>/dev/null)",
            "SYFT_BIN ?= $(shell command -v syft 2>/dev/null)",
        ),
        (
            "scripts/generate_release_manifest.py",
            'SYFT_VERSION = "1.49.0"',
            'SYFT_VERSION = "1.48.0"',
        ),
        (
            "scripts/generate_release_manifest.py",
            'CYCLONEDX_SPEC_VERSION = "1.7"',
            'CYCLONEDX_SPEC_VERSION = "1.6"',
        ),
        (
            "scripts/generate_release_manifest.py",
            'CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.7.schema.json"',
            'CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.6.schema.json"',
        ),
        (
            "scripts/generate_release_manifest.py",
            '    "apps/web/index.html",',
            '    "apps/web/renamed.html",',
        ),
        (
            "scripts/generate_release_manifest.py",
            '        "postgis-image.cdx.json",',
            '        "postgis-runtime.cdx.json",',
        ),
        (
            "scripts/generate_release_manifest.py",
            "sha256:d2fe6296c8ed5b21b31a426f51b9176b4d89f80a0a380632a7a833d604951273",
            "sha256:e2fe6296c8ed5b21b31a426f51b9176b4d89f80a0a380632a7a833d604951273",
        ),
        (
            "SUPPORT_MATRIX.md",
            "Syft 1.49.0",
            "Syft 1.48.0",
        ),
    ],
)
def test_syft_policy_drift_fails(
    tmp_path: Path, relative: str, old: str, new: str
) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / relative, old, new)

    assert "SYFT_POLICY_MISMATCH" in _finding_codes(root)


def test_syft_installer_action_commit_drift_fails(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(
        root / ".github/workflows/ci.yml",
        "e22c389904149dbc22b58101806040fa8d37a610",
        "f22c389904149dbc22b58101806040fa8d37a610",
    )

    codes = _finding_codes(root)
    assert "SYFT_POLICY_MISMATCH" in codes
    assert "REGISTER_VERSION_MISMATCH" in codes


def test_syft_internal_schema_is_audited(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def drift_schema(entries: list[dict[str, object]]) -> None:
        target = _entry(entries, "tool:syft")
        manifest = target["manifest"]
        assert isinstance(manifest, dict)
        manifest["internal_schema_version"] = "16.1.9"

    _edit_register(root, drift_schema)
    assert "SYFT_POLICY_MISMATCH" in _finding_codes(root)


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    [
        (
            "Makefile",
            "Keep syntax compatible with macOS GNU Make 3.81",
            "Keep syntax compatible with a recent Make",
        ),
        (
            "scripts/devctl.py",
            'shutil.which("git")',
            'shutil.which("other-vcs")',
        ),
        (
            "scripts/devctl.py",
            'shutil.which("lsof")',
            'shutil.which("netstat")',
        ),
        (
            "SUPPORT_MATRIX.md",
            "GNU Make >=3.81",
            "GNU Make >=4.4",
        ),
        (
            "SUPPORT_MATRIX.md",
            "Docker Compose >=2.24",
            "Docker Compose >=2.20",
        ),
        (
            "scripts/check_toolchain.py",
            "MINIMUM_COMPOSE_VERSION = (2, 24, 0)",
            "MINIMUM_COMPOSE_VERSION = (2, 20, 0)",
        ),
    ],
)
def test_host_tool_capability_policy_drift_fails(
    tmp_path: Path, relative: str, old: str, new: str
) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / relative, old, new)

    assert "HOST_TOOL_POLICY_MISMATCH" in _finding_codes(root)


def test_host_tool_validated_snapshot_is_audited(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def drift_git(entries: list[dict[str, object]]) -> None:
        _entry(entries, "tool:git")["version"] = "2.53.0"

    _edit_register(root, drift_git)
    assert "HOST_TOOL_POLICY_MISMATCH" in _finding_codes(root)


def test_compose_register_floor_is_audited(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def drift_compose_floor(entries: list[dict[str, object]]) -> None:
        target = _entry(entries, "tool:docker-compose")
        manifest = target["manifest"]
        assert isinstance(manifest, dict)
        manifest["supported_floor"] = "2.20.0"

    _edit_register(root, drift_compose_floor)
    assert "HOST_TOOL_POLICY_MISMATCH" in _finding_codes(root)


def test_minio_known_advisory_posture_is_required(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)

    def remove_advisory(entries: list[dict[str, object]]) -> None:
        target = _entry(entries, "source:minio-server")
        advisories = target["known_advisories"]
        assert isinstance(advisories, list)
        advisories.remove("GHSA-hv4r-mvr4-25vw")

    _edit_register(root, remove_advisory)
    assert "MINIO_ADVISORY_POSTURE_MISSING" in _finding_codes(root)


@pytest.mark.parametrize(
    ("relative", "old", "new", "expected"),
    [
        (
            "infra/minio/Dockerfile",
            "not approved for production",
            "approved for production",
            "MINIO_PRODUCTION_GUARD_MISSING",
        ),
        (
            "infra/minio/Dockerfile",
            "ARG MINIO_COMMIT=9e49d5e7",
            "ARG MINIO_COMMIT=0e49d5e7",
            "MINIO_SOURCE_PIN_MISMATCH",
        ),
        (
            "compose.yaml",
            "gatewaygs-ai-4-earth-hackathon/minio:RELEASE.2025",
            "gatewaygs-ai-4-earth-hackathon/minio:RELEASE.2024",
            "MINIO_LOCAL_IMAGE_MISMATCH",
        ),
    ],
)
def test_minio_manifest_guards(
    tmp_path: Path, relative: str, old: str, new: str, expected: str
) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / relative, old, new)

    assert expected in _finding_codes(root)


@pytest.mark.parametrize(
    ("relative", "old", "new", "expected"),
    [
        (
            "uv.lock",
            'hash = "sha256:',
            'hash = "sha512:',
            "UV_ARTIFACT_NOT_HASHED",
        ),
        (
            "pnpm-lock.yaml",
            "resolution: {integrity:",
            "resolution: {checksum:",
            "PNPM_TRANSITIVE_NOT_HASHED",
        ),
        (
            "pnpm-lock.yaml",
            "specifier: 4.4.3",
            "specifier: 4.4.2",
            "PNPM_IMPORTER_MISMATCH",
        ),
        (
            "uv.lock",
            "revision = 3",
            "revision = 2",
            "UV_LOCK_FORMAT_UNEXPECTED",
        ),
        (
            "pnpm-lock.yaml",
            "lockfileVersion: '9.0'",
            "lockfileVersion: '8.0'",
            "PNPM_LOCK_FORMAT_UNEXPECTED",
        ),
    ],
)
def test_lockfile_integrity_failures(
    tmp_path: Path, relative: str, old: str, new: str, expected: str
) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / relative, old, new)

    assert expected in _finding_codes(root)


@pytest.mark.parametrize(
    ("relative", "old", "new"),
    [
        (".python-version", "3.14.7", "3.14.6"),
        (".node-version", "24.19.0", "24.18.0"),
        (
            "pyproject.toml",
            'required-version = "==0.12.3"',
            'required-version = "==0.12.2"',
        ),
        (
            "package.json",
            '"packageManager": "pnpm@11.21.0"',
            '"packageManager": "pnpm@11.20.0"',
        ),
    ],
)
def test_tool_pin_drift_fails(
    tmp_path: Path, relative: str, old: str, new: str
) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / relative, old, new)

    assert "TOOL_PIN_MISMATCH" in _finding_codes(root)


def test_invalid_register_schema_fails_closed(tmp_path: Path) -> None:
    root = _copy_audit_root(tmp_path)
    _replace(root / "docs/dependencies.md", '"purpose":', '"missing-purpose":')

    assert "AUDIT_INPUT_INVALID" in _finding_codes(root)


def test_diagnostics_redact_secrets_and_url_userinfo() -> None:
    diagnostic = redact(
        "token=plain-value password: hunter2 https://alice:secret@example.test/path"
    )

    assert "plain-value" not in diagnostic
    assert "hunter2" not in diagnostic
    assert "alice:secret" not in diagnostic
    assert diagnostic.count("<redacted>") == EXPECTED_REDACTION_COUNT


@pytest.mark.parametrize(
    ("version", "range_expression", "expected"),
    [
        ("6.0.3", ">=4.8.4 <6.1.0", True),
        ("7.0.2", ">=4.8.4 <6.1.0", False),
        ("10.8.1", "^8.57.0 || ^9.0.0 || ^10.0.0", True),
        ("11.0.0", "^8.57.0 || ^9.0.0 || ^10.0.0", False),
        ("10.8.1", "^9 || ^10", True),
        ("not-semver", "*", False),
    ],
)
def test_semver_peer_range_evaluator(
    version: str, range_expression: str, *, expected: bool
) -> None:
    assert semver_satisfies(version, range_expression) is expected
