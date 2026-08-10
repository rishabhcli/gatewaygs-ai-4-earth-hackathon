"""Offline, deterministic audit of the repository's direct dependencies.

The canonical register is the JSON block in ``docs/dependencies.md``.  This
module deliberately uses only the Python standard library and reads only a
fixed set of repository manifests.  It never opens sockets, reads process
environment variables, or invokes package managers.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

REGISTER_START = "<!-- dependency-register:start -->"
REGISTER_END = "<!-- dependency-register:end -->"
EVIDENCE_COMMAND = (
    "uv run --frozen --offline python scripts/dependency_audit.py --write-evidence"
)

_EXACT_PYTHON_REQUIREMENT = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==(?P<version>[A-Za-z0-9_.+!-]+)$"
)
_EXACT_NPM_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_DIGEST_REF = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
_GITHUB_ACTION_USE = re.compile(
    r"""^\s*(?:-\s*)?(?P<key_quote>["']?)uses(?P=key_quote)\s*:\s*"""
    r"""(?P<reference>"[^"]*"|'[^']*'|\S+?)"""
    r"(?:\s+#\s*(?P<release_line>\S.*))?\s*$"
)
_GITHUB_ACTION_USE_KEY = re.compile(
    r"""(?:^|[{,])\s*(?:-\s*)?(?:["']uses["']|uses)\s*:"""
)
_IMMUTABLE_GITHUB_ACTION = re.compile(r"^(?P<name>[^@\s]+)@(?P<commit>[0-9a-f]{40})$")
_SECRET_VALUE = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_URL_USERINFO = re.compile(r"(https?://)[^/@\s]+@", re.IGNORECASE)
_SEMVER = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$")
_MIN_QUOTED_SCALAR_LENGTH = 2
_YAML_IMPORTER_INDENT = 2
_YAML_GROUP_INDENT = 4
_YAML_DEPENDENCY_INDENT = 6
_YAML_SPECIFIER_INDENT = 8
_UV_LOCK_REVISION = 3
_EXPECTED_MINIO_POLICY_ENTRIES = 2
_REQUIRED_TOOL_NAMES = frozenset(
    {
        "CPython",
        "Docker Compose",
        "Docker Engine",
        "GNU Make",
        "Git",
        "Node.js",
        "Syft",
        "lsof",
        "pnpm",
        "uv",
    }
)
_SYFT_VERSION = "1.49.0"
_SYFT_ACTION_REFERENCE = (
    "anchore/sbom-action/download-syft@e22c389904149dbc22b58101806040fa8d37a610"
)
_SYFT_ACTION_VERSION = "v0.24.0"
_CYCLONEDX_FORMAT = "JSON"
_CYCLONEDX_SPEC_VERSION = "1.7"
_CYCLONEDX_SCHEMA = "http://cyclonedx.org/schema/bom-1.7.schema.json"
_SYFT_INTERNAL_SCHEMA_VERSION = "16.1.10"
_MINIO_LOCAL_IMAGE = "gatewaygs-ai-4-earth-hackathon/minio:RELEASE.2025-10-15T17-29-55Z"
_POSTGIS_IMAGE = (
    "postgis/postgis:16-3.5-alpine@"
    "sha256:d2fe6296c8ed5b21b31a426f51b9176b4d89f80a0a380632a7a833d604951273"
)
_EXPECTED_RELEASE_OUTPUTS = frozenset(
    {
        "application-locks.cdx.json",
        "minio-image.cdx.json",
        "postgis-image.cdx.json",
        "release-manifest.json",
    }
)
_EXPECTED_RELEASE_INPUT_FILES = (
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
_EXPECTED_RELEASE_INPUT_DIRECTORIES = (
    "apps/web/public",
    "apps/web/src",
    "apps/web/tests",
)
_AUDIT_POLICY_INPUT_FILES = (
    "SUPPORT_MATRIX.md",
    "docs/dependencies.md",
    "scripts/check_boundaries.py",
    "scripts/check_toolchain.py",
    "scripts/dependency_audit.py",
    "scripts/devctl.py",
)
_AUDIT_POLICY_INPUT_DIRECTORIES = (".github/workflows",)
_OPTIONAL_LOCAL_ACTION_DIRECTORY = ".github/actions"
_REQUIRED_MINIO_ADVISORIES = frozenset(
    {
        "GHSA-3rh2-v3gr-35p9",
        "GHSA-5cx5-wh4m-82fh",
        "GHSA-9c4q-hq6p-c237",
        "GHSA-h749-fxx7-pwpg",
        "GHSA-hv4r-mvr4-25vw",
        "GHSA-jv87-32hw-hh99",
        "GHSA-xh8f-g2qw-gcm7",
    }
)

_REQUIRED_ENTRY_FIELDS = (
    "id",
    "kind",
    "name",
    "version",
    "scope",
    "manifest",
    "purpose",
    "license",
    "maintenance",
    "security",
    "native_binary",
    "cost",
    "update_trigger",
    "sources",
)


class AuditDataError(ValueError):
    """The register or a manifest is not structurally auditable."""


@dataclass(frozen=True, slots=True)
class RegisterEntry:
    """A validated dependency-register entry."""

    entry_id: str
    kind: str
    name: str
    version: str
    scope: str
    manifest: dict[str, str]
    purpose: str
    license: str
    maintenance: str
    security: str
    native_binary: str
    cost: str
    update_trigger: str
    sources: tuple[str, ...]
    production_approved: bool | None
    known_advisories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DirectDependency:
    """A direct dependency discovered from a package manifest."""

    kind: str
    name: str
    version: str | None
    raw_specifier: str
    path: str
    group: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One stable audit failure."""

    check: str
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Return a redacted, JSON-serializable finding."""

        return {
            "check": self.check,
            "code": self.code,
            "message": redact(self.message),
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class AuditReport:
    """Deterministic result of one offline audit."""

    entries: tuple[RegisterEntry, ...]
    direct_dependencies: tuple[DirectDependency, ...]
    findings: tuple[Finding, ...]
    input_hashes: tuple[tuple[str, str], ...]

    @property
    def passed(self) -> bool:
        """Whether every check passed."""

        return not self.findings

    def as_dict(self) -> dict[str, object]:
        """Return the stable evidence schema."""

        check_names = (
            "container-immutability",
            "direct-dependency-registration",
            "lockfile-integrity",
            "minio-production-policy",
            "register-schema",
            "tool-pins",
            "typescript-eslint-compatibility",
        )
        failed_checks = {finding.check for finding in self.findings}
        checks = [
            {
                "id": name,
                "status": "fail" if name in failed_checks else "pass",
            }
            for name in check_names
        ]
        direct_counts: dict[str, int] = {}
        for dependency in self.direct_dependencies:
            direct_counts[dependency.kind] = direct_counts.get(dependency.kind, 0) + 1
        registered_counts: dict[str, int] = {}
        for entry in self.entries:
            registered_counts[entry.kind] = registered_counts.get(entry.kind, 0) + 1

        return {
            "schema_version": 1,
            "command": EVIDENCE_COMMAND,
            "seed": None,
            "status": "pass" if self.passed else "fail",
            "network": {
                "mode": "offline-only",
                "used": False,
            },
            "summary": {
                "checks": len(check_names),
                "direct_dependencies": dict(sorted(direct_counts.items())),
                "findings": len(self.findings),
                "registered_entries": len(self.entries),
                "registered_entry_kinds": dict(sorted(registered_counts.items())),
            },
            "checks": checks,
            "findings": [finding.as_dict() for finding in self.findings],
            "inputs": [
                {"path": path, "sha256": digest} for path, digest in self.input_hashes
            ],
        }

    def to_json(self) -> str:
        """Serialize evidence canonically with a trailing newline."""

        return (
            json.dumps(
                self.as_dict(),
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
            )
            + "\n"
        )


def redact(value: str) -> str:
    """Structurally remove common credential shapes from diagnostics."""

    without_userinfo = _URL_USERINFO.sub(r"\1<redacted>@", value)
    return _SECRET_VALUE.sub(r"\1\2<redacted>", without_userinfo)


def _normalise_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _require_string(mapping: dict[str, object], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AuditDataError(f"{context}.{key} must be a non-empty string")
    return value


def _string_mapping(value: object, context: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise AuditDataError(f"{context} must be an object")
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str) or not item:
            raise AuditDataError(f"{context} keys and values must be non-empty strings")
        result[key] = item
    return result


def _https_sources(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise AuditDataError(f"{context} must be a non-empty array")
    if any(
        not isinstance(source, str) or not source.startswith("https://")
        for source in value
    ):
        raise AuditDataError(f"{context} must contain HTTPS URLs")
    return tuple(cast("list[str]", value))


def _optional_bool(value: object, context: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise AuditDataError(f"{context} must be boolean")
    return value


def _advisories(value: object, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise AuditDataError(f"{context} must be an array")
    if any(not isinstance(advisory, str) or not advisory for advisory in value):
        raise AuditDataError(f"{context} values must be non-empty strings")
    return tuple(cast("list[str]", value))


def _parse_entry(raw: dict[str, object], index: int) -> RegisterEntry:
    context = f"entries[{index}]"
    for field in _REQUIRED_ENTRY_FIELDS:
        if field not in raw:
            raise AuditDataError(f"{context} is missing required field {field!r}")

    manifest = _string_mapping(raw["manifest"], f"{context}.manifest")
    sources = _https_sources(raw["sources"], f"{context}.sources")
    approved = _optional_bool(
        raw.get("production_approved"), f"{context}.production_approved"
    )
    advisories = _advisories(
        raw.get("known_advisories", []), f"{context}.known_advisories"
    )

    return RegisterEntry(
        entry_id=_require_string(raw, "id", context),
        kind=_require_string(raw, "kind", context),
        name=_require_string(raw, "name", context),
        version=_require_string(raw, "version", context),
        scope=_require_string(raw, "scope", context),
        manifest=manifest,
        purpose=_require_string(raw, "purpose", context),
        license=_require_string(raw, "license", context),
        maintenance=_require_string(raw, "maintenance", context),
        security=_require_string(raw, "security", context),
        native_binary=_require_string(raw, "native_binary", context),
        cost=_require_string(raw, "cost", context),
        update_trigger=_require_string(raw, "update_trigger", context),
        sources=sources,
        production_approved=approved,
        known_advisories=advisories,
    )


def load_register(path: Path) -> tuple[RegisterEntry, ...]:
    """Load and validate the canonical JSON register embedded in Markdown."""

    text = path.read_text(encoding="utf-8")
    try:
        body = text.split(REGISTER_START, 1)[1].split(REGISTER_END, 1)[0]
    except IndexError as error:
        raise AuditDataError("dependency-register markers are missing") from error
    fenced = body.strip()
    if not fenced.startswith("```json") or not fenced.endswith("```"):
        raise AuditDataError("dependency-register body must be one JSON code fence")
    payload = fenced[len("```json") : -len("```")].strip()
    parsed: object = json.loads(payload)
    if not isinstance(parsed, dict):
        raise AuditDataError("dependency register root must be an object")
    schema_version = parsed.get("schema_version")
    if schema_version != 1:
        raise AuditDataError("dependency register schema_version must be 1")
    reviewed_on = parsed.get("reviewed_on")
    if not isinstance(reviewed_on, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", reviewed_on
    ):
        raise AuditDataError("dependency register reviewed_on must be YYYY-MM-DD")
    entries_raw = parsed.get("entries")
    if not isinstance(entries_raw, list):
        raise AuditDataError("dependency register entries must be an array")
    entries: list[RegisterEntry] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(entries_raw):
        if not isinstance(item, dict):
            raise AuditDataError(f"entries[{index}] must be an object")
        entry = _parse_entry(cast("dict[str, object]", item), index)
        if entry.entry_id in seen_ids:
            raise AuditDataError(f"duplicate register id: {entry.entry_id}")
        seen_ids.add(entry.entry_id)
        entries.append(entry)
    return tuple(entries)


def _toml(path: Path) -> dict[str, object]:
    parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise AuditDataError(f"{path.name} must contain a TOML object")
    return cast("dict[str, object]", parsed)


def _string_list(value: object, context: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise AuditDataError(f"{context} must be an array of strings")
    return cast("list[str]", value)


def _discover_python(root: Path, findings: list[Finding]) -> list[DirectDependency]:
    path = root / "pyproject.toml"
    parsed = _toml(path)
    project_raw = parsed.get("project")
    if not isinstance(project_raw, dict):
        raise AuditDataError("pyproject.toml [project] is missing")
    project = cast("dict[str, object]", project_raw)
    groups: list[tuple[str, list[str]]] = [
        (
            "project.dependencies",
            _string_list(project.get("dependencies"), "project.dependencies"),
        )
    ]
    dependency_groups_raw = parsed.get("dependency-groups", {})
    if not isinstance(dependency_groups_raw, dict):
        raise AuditDataError("pyproject.toml [dependency-groups] must be a table")
    dependency_groups = cast("dict[str, object]", dependency_groups_raw)
    groups.extend(
        (
            f"dependency-groups.{group_name}",
            _string_list(
                dependency_groups[group_name],
                f"dependency-groups.{group_name}",
            ),
        )
        for group_name in sorted(dependency_groups)
    )

    dependencies: list[DirectDependency] = []
    for group, specifications in groups:
        for specification in specifications:
            match = _EXACT_PYTHON_REQUIREMENT.fullmatch(specification)
            if match is None:
                name_match = re.match(r"[A-Za-z0-9_.-]+", specification)
                name = name_match.group(0) if name_match else specification
                findings.append(
                    Finding(
                        check="direct-dependency-registration",
                        code="UNPINNED_DIRECT_DEPENDENCY",
                        path="pyproject.toml",
                        message=(
                            f"Python direct dependency {specification!r} in {group} "
                            "is not pinned with == to one exact version"
                        ),
                    )
                )
                dependencies.append(
                    DirectDependency(
                        kind="python",
                        name=_normalise_python_name(name),
                        version=None,
                        raw_specifier=specification,
                        path="pyproject.toml",
                        group=group,
                    )
                )
                continue
            dependencies.append(
                DirectDependency(
                    kind="python",
                    name=_normalise_python_name(match.group("name")),
                    version=match.group("version"),
                    raw_specifier=specification,
                    path="pyproject.toml",
                    group=group,
                )
            )
    return dependencies


def _load_json_object(path: Path) -> dict[str, object]:
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise AuditDataError(f"{path} must contain a JSON object")
    return cast("dict[str, object]", parsed)


def _package_json_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("package.json"):
        relative_parts = path.relative_to(root).parts
        if any(
            part in {".dev", ".git", ".venv", "node_modules"} for part in relative_parts
        ):
            continue
        paths.append(path)
    return sorted(paths)


def _discover_npm(root: Path, findings: list[Finding]) -> list[DirectDependency]:
    dependencies: list[DirectDependency] = []
    dependency_groups = (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
        "peerDependencies",
    )
    for path in _package_json_paths(root):
        relative = path.relative_to(root).as_posix()
        package = _load_json_object(path)
        for group in dependency_groups:
            raw_dependencies = package.get(group, {})
            if not isinstance(raw_dependencies, dict):
                raise AuditDataError(f"{relative} {group} must be an object")
            for name, raw_version in sorted(raw_dependencies.items()):
                if not isinstance(name, str) or not isinstance(raw_version, str):
                    raise AuditDataError(
                        f"{relative} {group} keys and values must be strings"
                    )
                exact = _EXACT_NPM_VERSION.fullmatch(raw_version) is not None
                if not exact:
                    findings.append(
                        Finding(
                            check="direct-dependency-registration",
                            code="UNPINNED_DIRECT_DEPENDENCY",
                            path=relative,
                            message=(
                                f"npm direct dependency {name!r} in {group} uses "
                                f"non-exact specifier {raw_version!r}"
                            ),
                        )
                    )
                dependencies.append(
                    DirectDependency(
                        kind="npm",
                        name=name,
                        version=raw_version if exact else None,
                        raw_specifier=raw_version,
                        path=relative,
                        group=group,
                    )
                )
    return dependencies


def _github_action_manifest_paths(root: Path) -> list[Path]:
    workflow_root = root / ".github/workflows"
    manifests = sorted(
        path for path in workflow_root.iterdir() if path.suffix in {".yaml", ".yml"}
    )
    if not manifests:
        raise AuditDataError(".github/workflows has no workflow manifests")
    local_root = root / _OPTIONAL_LOCAL_ACTION_DIRECTORY
    if local_root.is_symlink():
        raise AuditDataError(".github/actions must not be a symlink")
    if local_root.exists():
        if not local_root.is_dir():
            raise AuditDataError(".github/actions must be a directory")
        manifests.extend(
            path
            for path in local_root.rglob("*")
            if path.name in {"action.yaml", "action.yml"}
        )
    return sorted(manifests)


def _github_action_uses(root: Path) -> list[tuple[str, int, str, str | None]]:
    uses: list[tuple[str, int, str, str | None]] = []
    for manifest_path in _github_action_manifest_paths(root):
        relative = manifest_path.relative_to(root).as_posix()
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise AuditDataError(f"workflow input is not a regular file: {relative}")
        manifest = manifest_path.read_text(encoding="utf-8")
        for line_number, line in enumerate(manifest.splitlines(), start=1):
            match = _GITHUB_ACTION_USE.fullmatch(line)
            if match is None:
                if _GITHUB_ACTION_USE_KEY.search(line):
                    raise AuditDataError(
                        f"non-canonical uses key at {relative}:{line_number}"
                    )
                continue
            reference = _yaml_scalar(match.group("reference"))
            if reference.startswith("./"):
                continue
            uses.append((relative, line_number, reference, match.group("release_line")))
    return uses


def _discover_github_actions(
    root: Path, findings: list[Finding]
) -> list[DirectDependency]:
    dependencies: list[DirectDependency] = []
    for path, line_number, reference, _release_line in _github_action_uses(root):
        immutable = _IMMUTABLE_GITHUB_ACTION.fullmatch(reference)
        if immutable is None:
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="UNPINNED_GITHUB_ACTION",
                    path=path,
                    message=(
                        f"external action on line {line_number} must use a full "
                        f"40-character commit, observed {reference!r}"
                    ),
                )
            )
            name, _, raw_version = reference.partition("@")
            dependencies.append(
                DirectDependency(
                    kind="github-action",
                    name=name,
                    version=None,
                    raw_specifier=raw_version,
                    path=path,
                    group="workflow.uses",
                )
            )
            continue
        dependencies.append(
            DirectDependency(
                kind="github-action",
                name=immutable.group("name"),
                version=immutable.group("commit"),
                raw_specifier=reference,
                path=path,
                group="workflow.uses",
            )
        )
    return dependencies


def _registry_key(entry: RegisterEntry) -> tuple[str, str, str, str]:
    path = entry.manifest.get("path", "")
    group = entry.manifest.get("group", "")
    name = _normalise_python_name(entry.name) if entry.kind == "python" else entry.name
    return entry.kind, path, group, name


def _dependency_key(dependency: DirectDependency) -> tuple[str, str, str, str]:
    return (
        dependency.kind,
        dependency.path,
        dependency.group,
        dependency.name,
    )


def _check_registration(
    entries: tuple[RegisterEntry, ...],
    dependencies: list[DirectDependency],
    findings: list[Finding],
) -> None:
    registry: dict[tuple[str, str, str, str], RegisterEntry] = {}
    for entry in entries:
        if entry.kind not in {"github-action", "npm", "python"}:
            continue
        key = _registry_key(entry)
        if key in registry:
            findings.append(
                Finding(
                    check="register-schema",
                    code="DUPLICATE_REGISTER_TARGET",
                    path="docs/dependencies.md",
                    message=f"multiple entries target {key}",
                )
            )
        registry[key] = entry

    discovered_keys: set[tuple[str, str, str, str]] = set()
    for dependency in dependencies:
        key = _dependency_key(dependency)
        discovered_keys.add(key)
        registered = registry.get(key)
        if registered is None:
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="UNREGISTERED_DIRECT_DEPENDENCY",
                    path=dependency.path,
                    message=(
                        f"{dependency.kind} direct dependency {dependency.name!r} "
                        f"in {dependency.group} has no register entry"
                    ),
                )
            )
        elif (
            dependency.version is not None and registered.version != dependency.version
        ):
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="REGISTER_VERSION_MISMATCH",
                    path="docs/dependencies.md",
                    message=(
                        f"{registered.entry_id} records {registered.version}, but "
                        f"{dependency.path} pins {dependency.version}"
                    ),
                )
            )

    for key, registered in sorted(registry.items()):
        if key not in discovered_keys:
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="STALE_REGISTER_ENTRY",
                    path="docs/dependencies.md",
                    message=(
                        f"{registered.entry_id} does not map to a direct dependency"
                    ),
                )
            )


def _check_github_action_metadata(
    root: Path, entries: tuple[RegisterEntry, ...], findings: list[Finding]
) -> None:
    observed = {
        (path, reference): release_line
        for path, _line_number, reference, release_line in _github_action_uses(root)
    }
    for entry in entries:
        if entry.kind != "github-action":
            continue
        expected_reference = f"{entry.name}@{entry.version}"
        registered_reference = entry.manifest.get("reference")
        if registered_reference != expected_reference:
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="GITHUB_ACTION_REFERENCE_MISMATCH",
                    path="docs/dependencies.md",
                    message=(
                        f"{entry.entry_id} reference is {registered_reference!r}; "
                        f"expected {expected_reference!r}"
                    ),
                )
            )
        release_line = entry.manifest.get("release_line")
        manifest_path = entry.manifest.get("path", "")
        observed_release_line = observed.get((manifest_path, expected_reference))
        if observed_release_line != release_line:
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="GITHUB_ACTION_RELEASE_LINE_MISMATCH",
                    path=".github/workflows/ci.yml",
                    message=(
                        f"{expected_reference} annotation is "
                        f"{observed_release_line!r}; register says "
                        f"{release_line!r}"
                    ),
                )
            )


def _uv_package(raw_package: object, index: int) -> tuple[dict[str, object], str, str]:
    if not isinstance(raw_package, dict):
        raise AuditDataError(f"uv.lock package[{index}] must be a table")
    package = cast("dict[str, object]", raw_package)
    name = package.get("name")
    version = package.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise AuditDataError(f"uv.lock package[{index}] lacks name/version")
    return package, name, version


def _uv_artifacts_hashed(package: dict[str, object]) -> bool:
    artifacts: list[dict[str, object]] = []
    sdist = package.get("sdist")
    if isinstance(sdist, dict):
        artifacts.append(cast("dict[str, object]", sdist))
    wheels = package.get("wheels")
    if isinstance(wheels, list):
        artifacts.extend(
            cast("dict[str, object]", wheel)
            for wheel in wheels
            if isinstance(wheel, dict)
        )
    return bool(artifacts) and all(
        isinstance(artifact.get("hash"), str)
        and cast("str", artifact["hash"]).startswith("sha256:")
        for artifact in artifacts
    )


def _check_uv_lock(
    root: Path,
    dependencies: list[DirectDependency],
    findings: list[Finding],
) -> None:
    lock_path = root / "uv.lock"
    lock = _toml(lock_path)
    if lock.get("version") != 1 or lock.get("revision") != _UV_LOCK_REVISION:
        findings.append(
            Finding(
                check="lockfile-integrity",
                code="UV_LOCK_FORMAT_UNEXPECTED",
                path="uv.lock",
                message=(
                    f"uv.lock version/revision are {lock.get('version')!r}/"
                    f"{lock.get('revision')!r}; expected 1/3"
                ),
            )
        )
    packages_raw = lock.get("package")
    if not isinstance(packages_raw, list):
        raise AuditDataError("uv.lock package list is missing")
    locked: set[tuple[str, str]] = set()
    for index, raw_package in enumerate(packages_raw):
        package, name, version = _uv_package(raw_package, index)
        source = package.get("source")
        locked.add((_normalise_python_name(name), version))
        if not isinstance(source, dict) or "registry" not in source:
            continue
        if not _uv_artifacts_hashed(package):
            findings.append(
                Finding(
                    check="lockfile-integrity",
                    code="UV_ARTIFACT_NOT_HASHED",
                    path="uv.lock",
                    message=f"locked package {name}=={version} lacks artifact hashes",
                )
            )

    for dependency in dependencies:
        if dependency.kind != "python" or dependency.version is None:
            continue
        if (dependency.name, dependency.version) not in locked:
            findings.append(
                Finding(
                    check="lockfile-integrity",
                    code="DIRECT_DEPENDENCY_NOT_LOCKED",
                    path="uv.lock",
                    message=(
                        f"{dependency.name}=={dependency.version} is not present "
                        "in uv.lock"
                    ),
                )
            )


def _yaml_scalar(value: str) -> str:
    stripped = value.strip()
    if (
        len(stripped) >= _MIN_QUOTED_SCALAR_LENGTH
        and stripped[0] == stripped[-1]
        and stripped[0] in "'\""
    ):
        return stripped[1:-1]
    return stripped


def _pnpm_importers(text: str) -> dict[tuple[str, str, str], str]:
    result: dict[tuple[str, str, str], str] = {}
    in_importers = False
    importer: str | None = None
    group: str | None = None
    dependency: str | None = None
    for line in text.splitlines():
        if line == "importers:":
            in_importers = True
            continue
        if in_importers and line == "packages:":
            break
        if not in_importers or not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == _YAML_IMPORTER_INDENT and stripped.endswith(":"):
            importer = _yaml_scalar(stripped[:-1])
            group = None
            dependency = None
        elif indent == _YAML_GROUP_INDENT and stripped.endswith(":"):
            group = _yaml_scalar(stripped[:-1])
            dependency = None
        elif indent == _YAML_DEPENDENCY_INDENT and stripped.endswith(":"):
            dependency = _yaml_scalar(stripped[:-1])
        elif (
            indent == _YAML_SPECIFIER_INDENT
            and stripped.startswith("specifier:")
            and importer is not None
            and group is not None
            and dependency is not None
        ):
            result[(importer, group, dependency)] = _yaml_scalar(
                stripped.split(":", 1)[1]
            )
    return result


def _pnpm_package_metadata(
    text: str,
) -> tuple[set[str], set[str], dict[str, dict[str, str]]]:
    seen: set[str] = set()
    hashed: set[str] = set()
    peers: dict[str, dict[str, str]] = {}
    try:
        section = text.split("\npackages:\n", 1)[1].split("\nsnapshots:\n", 1)[0]
    except IndexError as error:
        raise AuditDataError("pnpm-lock.yaml package sections are missing") from error
    blocks = re.split(r"(?m)(?=^  \S)", section)
    for block in blocks:
        lines = block.splitlines()
        if not lines or not lines[0].startswith("  "):
            continue
        package = _yaml_scalar(lines[0].strip()[:-1])
        seen.add(package)
        peers[package] = {}
        if re.search(r"(?m)^    resolution:.*\bintegrity:", block):
            hashed.add(package)
        peer_match = re.search(
            r"(?m)^    peerDependencies:\n(?P<body>(?:      .+\n?)*)",
            block,
        )
        if peer_match is None:
            continue
        for peer_line in peer_match.group("body").splitlines():
            name, raw_range = peer_line.strip().split(":", 1)
            peers[package][_yaml_scalar(name)] = _yaml_scalar(raw_range)
    return seen, hashed, peers


def _pnpm_package_key(name: str, version: str) -> str:
    return f"{name}@{version}"


def _check_pnpm_lock(
    root: Path,
    dependencies: list[DirectDependency],
    findings: list[Finding],
) -> dict[str, dict[str, str]]:
    path = root / "pnpm-lock.yaml"
    text = path.read_text(encoding="utf-8")
    if re.search(r"(?m)^lockfileVersion: ['\"]?9\.0['\"]?$", text) is None:
        findings.append(
            Finding(
                check="lockfile-integrity",
                code="PNPM_LOCK_FORMAT_UNEXPECTED",
                path="pnpm-lock.yaml",
                message="pnpm lockfileVersion must remain exactly 9.0",
            )
        )
    importers = _pnpm_importers(text)
    seen_packages, hashed_packages, peers = _pnpm_package_metadata(text)
    findings.extend(
        Finding(
            check="lockfile-integrity",
            code="PNPM_TRANSITIVE_NOT_HASHED",
            path="pnpm-lock.yaml",
            message=f"{package_key} lacks an integrity-pinned resolution",
        )
        for package_key in sorted(seen_packages - hashed_packages)
    )
    for dependency in dependencies:
        if dependency.kind != "npm" or dependency.version is None:
            continue
        importer = str(Path(dependency.path).parent)
        if importer == ".":
            importer = "."
        importer = importer.replace("\\", "/")
        importer_value = importers.get((importer, dependency.group, dependency.name))
        if importer_value != dependency.version:
            findings.append(
                Finding(
                    check="lockfile-integrity",
                    code="PNPM_IMPORTER_MISMATCH",
                    path="pnpm-lock.yaml",
                    message=(
                        f"{importer} {dependency.group} {dependency.name} is "
                        f"{importer_value!r} in lockfile, expected "
                        f"{dependency.version!r}"
                    ),
                )
            )
        package_key = _pnpm_package_key(dependency.name, dependency.version)
        if package_key not in hashed_packages:
            findings.append(
                Finding(
                    check="lockfile-integrity",
                    code="PNPM_PACKAGE_NOT_HASHED",
                    path="pnpm-lock.yaml",
                    message=f"{package_key} lacks an integrity-pinned package entry",
                )
            )
    return peers


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    match = _SEMVER.fullmatch(version.strip())
    if match is None:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor or "0"), int(patch or "0")


def _compare(
    left: tuple[int, int, int], operator: str, right: tuple[int, int, int]
) -> bool:
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    return left == right


def _satisfies_clause(version: tuple[int, int, int], clause: str) -> bool:
    tokens = clause.split()
    for token in tokens:
        if token in {"", "*"}:
            continue
        if token.startswith("^"):
            lower = _parse_semver(token[1:])
            if lower is None:
                return False
            if lower[0] > 0:
                upper = (lower[0] + 1, 0, 0)
            elif lower[1] > 0:
                upper = (0, lower[1] + 1, 0)
            else:
                upper = (0, 0, lower[2] + 1)
            if not (lower <= version < upper):
                return False
            continue
        match = re.fullmatch(r"(>=|<=|>|<|=)?(.+)", token)
        if match is None:
            return False
        expected = _parse_semver(match.group(2))
        if expected is None or not _compare(version, match.group(1) or "=", expected):
            return False
    return True


def semver_satisfies(version: str, range_expression: str) -> bool:
    """Evaluate the comparator/caret subset used by pnpm peer ranges."""

    parsed = _parse_semver(version)
    if parsed is None:
        return False
    return any(
        _satisfies_clause(parsed, clause.strip())
        for clause in range_expression.split("||")
    )


def _check_typescript_eslint(
    dependencies: list[DirectDependency],
    peers: dict[str, dict[str, str]],
    findings: list[Finding],
) -> None:
    npm_versions = {
        dependency.name: dependency.version
        for dependency in dependencies
        if dependency.kind == "npm" and dependency.version is not None
    }
    for package_name, package_version in sorted(npm_versions.items()):
        package_peers = peers.get(_pnpm_package_key(package_name, package_version), {})
        for peer_name in ("eslint", "typescript"):
            peer_range = package_peers.get(peer_name)
            installed = npm_versions.get(peer_name)
            if peer_range is None or installed is None:
                continue
            if not semver_satisfies(installed, peer_range):
                findings.append(
                    Finding(
                        check="typescript-eslint-compatibility",
                        code="INCOMPATIBLE_TYPESCRIPT_ESLINT_PIN",
                        path="apps/web/package.json",
                        message=(
                            f"{package_name}@{package_version} requires {peer_name} "
                            f"{peer_range}, but {installed} is pinned"
                        ),
                    )
                )
    eslint = npm_versions.get("eslint")
    eslint_js = npm_versions.get("@eslint/js")
    if eslint is not None and eslint_js is not None:
        eslint_major = _parse_semver(eslint)
        eslint_js_major = _parse_semver(eslint_js)
        if (
            eslint_major is None
            or eslint_js_major is None
            or eslint_major[0] != eslint_js_major[0]
        ):
            findings.append(
                Finding(
                    check="typescript-eslint-compatibility",
                    code="INCOMPATIBLE_ESLINT_JS_PIN",
                    path="apps/web/package.json",
                    message=(
                        f"eslint@{eslint} and @eslint/js@{eslint_js} must share a major"
                    ),
                )
            )


def _compose_services(text: str) -> dict[str, dict[str, str]]:
    services: dict[str, dict[str, str]] = {}
    in_services = False
    service: str | None = None
    for line in text.splitlines():
        if line == "services:":
            in_services = True
            continue
        if not in_services or not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            break
        if indent == _YAML_IMPORTER_INDENT and stripped.endswith(":"):
            service = stripped[:-1]
            services[service] = {}
        elif indent == _YAML_GROUP_INDENT and service is not None and ":" in stripped:
            key, value = stripped.split(":", 1)
            services[service][key] = _yaml_scalar(value)
    return services


def _external_container_refs(root: Path) -> list[tuple[str, str, str]]:
    refs: list[tuple[str, str, str]] = []
    compose_path = root / "compose.yaml"
    compose = _compose_services(compose_path.read_text(encoding="utf-8"))
    for service, attributes in sorted(compose.items()):
        image = attributes.get("image")
        if image and "build" not in attributes:
            refs.append(("compose.yaml", f"service:{service}", image))

    dockerfile_path = root / "infra/minio/Dockerfile"
    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    for line_number, line in enumerate(dockerfile.splitlines(), start=1):
        syntax_match = re.match(r"\s*#\s*syntax=(\S+)", line)
        if syntax_match:
            refs.append(
                (
                    "infra/minio/Dockerfile",
                    f"syntax:{line_number}",
                    syntax_match.group(1),
                )
            )
        from_match = re.match(r"\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line)
        if from_match:
            refs.append(
                (
                    "infra/minio/Dockerfile",
                    f"from:{line_number}",
                    from_match.group(1),
                )
            )
    return refs


def _check_containers(
    root: Path, entries: tuple[RegisterEntry, ...], findings: list[Finding]
) -> None:
    refs = _external_container_refs(root)
    registered_refs: dict[str, RegisterEntry] = {}
    for entry in entries:
        reference = entry.manifest.get("reference")
        if entry.kind == "container" and reference is not None:
            registered_refs[reference] = entry
    discovered: set[str] = set()
    for path, locator, reference in refs:
        discovered.add(reference)
        if _DIGEST_REF.fullmatch(reference) is None:
            findings.append(
                Finding(
                    check="container-immutability",
                    code="MUTABLE_CONTAINER_REFERENCE",
                    path=path,
                    message=f"{locator} uses mutable external reference {reference!r}",
                )
            )
        if reference not in registered_refs:
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="UNREGISTERED_CONTAINER",
                    path=path,
                    message=f"{locator} reference {reference!r} is not registered",
                )
            )
    for reference, entry in sorted(registered_refs.items()):
        if entry.manifest.get("local_build") == "true":
            continue
        if reference not in discovered:
            findings.append(
                Finding(
                    check="direct-dependency-registration",
                    code="STALE_REGISTER_ENTRY",
                    path="docs/dependencies.md",
                    message=f"{entry.entry_id} container reference was not discovered",
                )
            )


def _check_version_files(
    root: Path, tools: dict[str, RegisterEntry], findings: list[Finding]
) -> None:
    expected_paths = {"CPython": ".python-version", "Node.js": ".node-version"}
    for name, path in expected_paths.items():
        tool_entry = tools.get(name)
        if tool_entry is None:
            findings.append(
                Finding(
                    check="tool-pins",
                    code="UNREGISTERED_TOOL",
                    path=path,
                    message=f"{name} has no tool register entry",
                )
            )
            continue
        actual = (root / path).read_text(encoding="utf-8").strip()
        if actual != tool_entry.version:
            findings.append(
                Finding(
                    check="tool-pins",
                    code="TOOL_PIN_MISMATCH",
                    path=path,
                    message=(
                        f"{name} is pinned to {actual}, register says "
                        f"{tool_entry.version}"
                    ),
                )
            )


def _check_uv_tool(
    pyproject: dict[str, object],
    tools: dict[str, RegisterEntry],
    findings: list[Finding],
) -> None:
    tool_raw = pyproject.get("tool")
    uv_required: object = None
    if isinstance(tool_raw, dict):
        uv_raw = tool_raw.get("uv")
        if isinstance(uv_raw, dict):
            uv_required = uv_raw.get("required-version")
    uv_entry = tools.get("uv")
    expected_uv = f"=={uv_entry.version}" if uv_entry is not None else None
    if uv_entry is None or uv_required != expected_uv:
        findings.append(
            Finding(
                check="tool-pins",
                code="TOOL_PIN_MISMATCH",
                path="pyproject.toml",
                message=(
                    f"tool.uv.required-version is {uv_required!r}; expected "
                    f"{expected_uv!r}"
                ),
            )
        )


def _check_javascript_tools(
    root: Path, tools: dict[str, RegisterEntry], findings: list[Finding]
) -> None:
    package = _load_json_object(root / "package.json")
    manager = package.get("packageManager")
    pnpm_entry = tools.get("pnpm")
    expected_manager = f"pnpm@{pnpm_entry.version}" if pnpm_entry else None
    if manager != expected_manager:
        findings.append(
            Finding(
                check="tool-pins",
                code="TOOL_PIN_MISMATCH",
                path="package.json",
                message=f"packageManager is {manager!r}; expected {expected_manager!r}",
            )
        )
    engines_raw = package.get("engines")
    engines = (
        cast("dict[str, object]", engines_raw) if isinstance(engines_raw, dict) else {}
    )
    expected_pnpm = pnpm_entry.version if pnpm_entry is not None else None
    if engines.get("pnpm") != expected_pnpm:
        findings.append(
            Finding(
                check="tool-pins",
                code="TOOL_PIN_MISMATCH",
                path="package.json",
                message=(
                    f"engines.pnpm is {engines.get('pnpm')!r}; expected "
                    f"{expected_pnpm!r}"
                ),
            )
        )
    node_entry = tools.get("Node.js")
    node_range = engines.get("node")
    if (
        node_entry is None
        or not isinstance(node_range, str)
        or not semver_satisfies(node_entry.version, node_range)
    ):
        findings.append(
            Finding(
                check="tool-pins",
                code="TOOL_ENGINE_INCOMPATIBLE",
                path="package.json",
                message=(
                    f"registered Node {node_entry.version if node_entry else None} "
                    f"does not satisfy engines.node {node_range!r}"
                ),
            )
        )


def _check_python_tool_range(
    pyproject: dict[str, object],
    tools: dict[str, RegisterEntry],
    findings: list[Finding],
) -> None:
    python_entry = tools.get("CPython")
    project_raw = pyproject.get("project")
    requires_python: object = None
    if isinstance(project_raw, dict):
        requires_python = project_raw.get("requires-python")
    expected_python = (
        f">={python_entry.version},<3.15" if python_entry is not None else None
    )
    if requires_python != expected_python:
        findings.append(
            Finding(
                check="tool-pins",
                code="TOOL_ENGINE_INCOMPATIBLE",
                path="pyproject.toml",
                message=(
                    f"project.requires-python is {requires_python!r}; expected "
                    f"{expected_python!r}"
                ),
            )
        )


def _literal_assignment_value(node: ast.expr, path: Path, name: str) -> object:
    try:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "frozenset"
            and len(node.args) == 1
            and not node.keywords
        ):
            literal = cast("object", ast.literal_eval(node.args[0]))
            if isinstance(literal, (list, set, tuple)):
                return frozenset(literal)
        else:
            return cast("object", ast.literal_eval(node))
    except (ValueError, TypeError) as error:
        raise AuditDataError(f"{path.name} {name} must be a literal") from error
    raise AuditDataError(f"{path.name} {name} must be a literal collection")


def _literal_module_assignments(path: Path, names: frozenset[str]) -> dict[str, object]:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as error:
        raise AuditDataError(f"{path.name} is not valid Python: {error.msg}") from error
    assignments: dict[str, object] = {}
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in names:
            continue
        assignments[target.id] = _literal_assignment_value(node.value, path, target.id)
    missing = names.difference(assignments)
    if missing:
        raise AuditDataError(f"{path.name} lacks literal assignments {sorted(missing)}")
    return assignments


def _syft_policy_finding(path: str, message: str) -> Finding:
    return Finding(
        check="tool-pins",
        code="SYFT_POLICY_MISMATCH",
        path=path,
        message=message,
    )


def _check_syft_generator(root: Path, findings: list[Finding]) -> None:
    generator_path = root / "scripts/generate_release_manifest.py"
    generator = _literal_module_assignments(
        generator_path,
        frozenset(
            {
                "CYCLONEDX_SCHEMA",
                "CYCLONEDX_SPEC_VERSION",
                "EXPECTED_OUTPUTS",
                "MINIO_IMAGE",
                "POSTGIS_IMAGE",
                "RELEASE_INPUTS",
                "RELEASE_INPUT_DIRECTORIES",
                "SYFT_VERSION",
            }
        ),
    )
    expected_generator: dict[str, object] = {
        "CYCLONEDX_SCHEMA": _CYCLONEDX_SCHEMA,
        "CYCLONEDX_SPEC_VERSION": _CYCLONEDX_SPEC_VERSION,
        "EXPECTED_OUTPUTS": _EXPECTED_RELEASE_OUTPUTS,
        "MINIO_IMAGE": _MINIO_LOCAL_IMAGE,
        "POSTGIS_IMAGE": _POSTGIS_IMAGE,
        "RELEASE_INPUTS": _EXPECTED_RELEASE_INPUT_FILES,
        "RELEASE_INPUT_DIRECTORIES": _EXPECTED_RELEASE_INPUT_DIRECTORIES,
        "SYFT_VERSION": _SYFT_VERSION,
    }
    for name, expected in expected_generator.items():
        observed = generator.get(name)
        if observed != expected:
            findings.append(
                _syft_policy_finding(
                    "scripts/generate_release_manifest.py",
                    f"{name} is {observed!r}; expected {expected!r}",
                )
            )


def _check_syft_tool(
    root: Path, tools: dict[str, RegisterEntry], findings: list[Finding]
) -> None:
    syft = tools.get("Syft")
    if syft is None:
        return
    if syft.version != _SYFT_VERSION:
        findings.append(
            _syft_policy_finding(
                "docs/dependencies.md",
                (
                    f"Syft register version is {syft.version!r}; expected "
                    f"{_SYFT_VERSION!r}"
                ),
            )
        )
    expected_manifest = {
        "path": ".github/workflows/ci.yml",
        "group": "download-syft",
        "installer_action": _SYFT_ACTION_REFERENCE,
        "installer_action_version": _SYFT_ACTION_VERSION,
        "cyclonedx_format": _CYCLONEDX_FORMAT,
        "cyclonedx_spec_version": _CYCLONEDX_SPEC_VERSION,
        "cyclonedx_schema": _CYCLONEDX_SCHEMA,
        "internal_schema_version": _SYFT_INTERNAL_SCHEMA_VERSION,
        "sbom_outputs": (
            "application-locks.cdx.json,minio-image.cdx.json,postgis-image.cdx.json"
        ),
        "release_manifest": "release-manifest.json",
        "scanned_images": f"{_MINIO_LOCAL_IMAGE},{_POSTGIS_IMAGE}",
    }
    for key, expected in expected_manifest.items():
        observed = syft.manifest.get(key)
        if observed != expected:
            findings.append(
                _syft_policy_finding(
                    "docs/dependencies.md",
                    f"tool:syft manifest {key} is {observed!r}; expected {expected!r}",
                )
            )

    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    expected_action_line = f"uses: {_SYFT_ACTION_REFERENCE} # {_SYFT_ACTION_VERSION}"
    expected_version_line = f"syft-version: v{_SYFT_VERSION}"
    if expected_action_line not in workflow:
        findings.append(
            _syft_policy_finding(
                ".github/workflows/ci.yml",
                "Syft installer action commit or release annotation drifted",
            )
        )
    if expected_version_line not in workflow:
        findings.append(
            _syft_policy_finding(
                ".github/workflows/ci.yml",
                f"Syft installer must request exactly v{_SYFT_VERSION}",
            )
        )

    makefile = (root / "Makefile").read_text(encoding="utf-8")
    if (
        re.search(rf"(?m)^SYFT_VERSION := {re.escape(_SYFT_VERSION)}$", makefile)
        is None
    ):
        findings.append(
            _syft_policy_finding(
                "Makefile", f"SYFT_VERSION must remain exactly {_SYFT_VERSION}"
            )
        )
    expected_syft_resolver = "override SYFT_BIN := $(shell command -v syft 2>/dev/null)"
    if expected_syft_resolver not in makefile:
        findings.append(
            _syft_policy_finding(
                "Makefile", "Syft executable resolution must be PATH-canonical"
            )
        )

    _check_syft_generator(root, findings)

    support_matrix = (root / "SUPPORT_MATRIX.md").read_text(encoding="utf-8")
    if f"Syft {_SYFT_VERSION}" not in support_matrix:
        findings.append(
            _syft_policy_finding(
                "SUPPORT_MATRIX.md",
                f"local host support must declare Syft {_SYFT_VERSION}",
            )
        )


def _check_host_capability_tools(
    root: Path, tools: dict[str, RegisterEntry], findings: list[Finding]
) -> None:
    expected = {
        "Docker Engine": (
            "29.6.2",
            "supported_floor",
            "24.0.0",
        ),
        "Docker Compose": (
            "5.3.1",
            "supported_floor",
            "2.24.0",
        ),
        "GNU Make": (
            "3.81",
            "supported_floor",
            "3.81",
        ),
        "Git": (
            "2.54.0",
            "supported_capability",
            "git -C <root> check-ignore --quiet .dev/probe",
        ),
        "lsof": (
            "4.91",
            "supported_capability",
            "lsof -nP -iTCP:<port> -sTCP:LISTEN -Fpcn",
        ),
    }
    for name, (version, policy_key, policy_value) in expected.items():
        entry = tools.get(name)
        if entry is None:
            continue
        if entry.version != version or entry.manifest.get(policy_key) != policy_value:
            findings.append(
                Finding(
                    check="tool-pins",
                    code="HOST_TOOL_POLICY_MISMATCH",
                    path="docs/dependencies.md",
                    message=(
                        f"{name} validated snapshot/capability drifted from "
                        f"{version!r} and {policy_value!r}"
                    ),
                )
            )

    makefile = (root / "Makefile").read_text(encoding="utf-8")
    if "Keep syntax compatible with macOS GNU Make 3.81" not in makefile:
        findings.append(
            Finding(
                check="tool-pins",
                code="HOST_TOOL_POLICY_MISMATCH",
                path="Makefile",
                message="Makefile must retain its GNU Make 3.81 compatibility contract",
            )
        )
    devctl = (root / "scripts/devctl.py").read_text(encoding="utf-8")
    required_devctl_fragments = (
        'shutil.which("git")',
        '"check-ignore"',
        'shutil.which("lsof")',
        '"-sTCP:LISTEN"',
        '"-Fpcn"',
    )
    if any(fragment not in devctl for fragment in required_devctl_fragments):
        findings.append(
            Finding(
                check="tool-pins",
                code="HOST_TOOL_POLICY_MISMATCH",
                path="scripts/devctl.py",
                message="devctl Git/lsof fail-closed capability probes drifted",
            )
        )
    support = (root / "SUPPORT_MATRIX.md").read_text(encoding="utf-8")
    required_support_fragments = (
        "Docker Engine >=24",
        "Docker Compose >=2.24",
        "GNU Make >=3.81",
        "Git with `check-ignore`",
        "lsof with bounded TCP/listener field output",
    )
    if any(fragment not in support for fragment in required_support_fragments):
        findings.append(
            Finding(
                check="tool-pins",
                code="HOST_TOOL_POLICY_MISMATCH",
                path="SUPPORT_MATRIX.md",
                message=(
                    "support matrix lacks required Docker/Compose/Make/Git/lsof "
                    "capabilities"
                ),
            )
        )

    toolchain_policy = _literal_module_assignments(
        root / "scripts/check_toolchain.py",
        frozenset({"MINIMUM_COMPOSE_VERSION", "MINIMUM_DOCKER_VERSION"}),
    )
    expected_toolchain_policy: dict[str, object] = {
        "MINIMUM_COMPOSE_VERSION": (2, 24, 0),
        "MINIMUM_DOCKER_VERSION": (24, 0, 0),
    }
    if toolchain_policy != expected_toolchain_policy:
        findings.append(
            Finding(
                check="tool-pins",
                code="HOST_TOOL_POLICY_MISMATCH",
                path="scripts/check_toolchain.py",
                message="Docker/Compose supported floors drifted",
            )
        )


def _check_tools(
    root: Path, entries: tuple[RegisterEntry, ...], findings: list[Finding]
) -> None:
    tools = {entry.name: entry for entry in entries if entry.kind == "tool"}
    findings.extend(
        Finding(
            check="tool-pins",
            code="UNREGISTERED_TOOL",
            path="docs/dependencies.md",
            message=f"{name} has no tool register entry",
        )
        for name in sorted(_REQUIRED_TOOL_NAMES - tools.keys())
    )
    pyproject = _toml(root / "pyproject.toml")
    _check_version_files(root, tools, findings)
    _check_uv_tool(pyproject, tools, findings)
    _check_javascript_tools(root, tools, findings)
    _check_python_tool_range(pyproject, tools, findings)
    _check_syft_tool(root, tools, findings)
    _check_host_capability_tools(root, tools, findings)


def _check_minio_entry(entry: RegisterEntry, findings: list[Finding]) -> None:
    if entry.production_approved is not False:
        findings.append(
            Finding(
                check="minio-production-policy",
                code="MINIO_PRODUCTION_APPROVAL_FORBIDDEN",
                path="docs/dependencies.md",
                message=f"{entry.entry_id} must set production_approved to false",
            )
        )
    missing = _REQUIRED_MINIO_ADVISORIES.difference(entry.known_advisories)
    if missing:
        findings.append(
            Finding(
                check="minio-production-policy",
                code="MINIO_ADVISORY_POSTURE_MISSING",
                path="docs/dependencies.md",
                message=f"{entry.entry_id} is missing advisories {sorted(missing)}",
            )
        )


def _check_minio_source_args(
    source_entry: RegisterEntry | None,
    dockerfile: str,
    findings: list[Finding],
) -> None:
    if source_entry is None:
        return
    expected_args = {
        "MINIO_COMMIT": source_entry.manifest.get("commit"),
        "MINIO_RELEASE": source_entry.version,
        "MINIO_SOURCE_SHA256": source_entry.manifest.get("source_sha256"),
    }
    for argument, expected in sorted(expected_args.items()):
        match = re.search(rf"(?m)^ARG {argument}=(\S+)$", dockerfile)
        actual = match.group(1) if match else None
        if expected is None or actual != expected:
            findings.append(
                Finding(
                    check="minio-production-policy",
                    code="MINIO_SOURCE_PIN_MISMATCH",
                    path="infra/minio/Dockerfile",
                    message=f"{argument} is {actual!r}; register says {expected!r}",
                )
            )


def _check_minio_local_image(
    root: Path,
    local_entry: RegisterEntry | None,
    findings: list[Finding],
) -> None:
    if local_entry is None:
        return
    compose = _compose_services((root / "compose.yaml").read_text(encoding="utf-8"))
    actual = compose.get("minio", {}).get("image")
    expected = local_entry.manifest.get("reference")
    if actual != expected:
        findings.append(
            Finding(
                check="minio-production-policy",
                code="MINIO_LOCAL_IMAGE_MISMATCH",
                path="compose.yaml",
                message=f"MinIO image is {actual!r}; register says {expected!r}",
            )
        )


def _check_minio_policy(
    root: Path, entries: tuple[RegisterEntry, ...], findings: list[Finding]
) -> None:
    minio_entries = tuple(
        entry
        for entry in entries
        if entry.name in {"MinIO server source", "MinIO local image"}
    )
    if len(minio_entries) != _EXPECTED_MINIO_POLICY_ENTRIES:
        findings.append(
            Finding(
                check="minio-production-policy",
                code="MINIO_POLICY_ENTRY_MISSING",
                path="docs/dependencies.md",
                message="MinIO source and local-image policy entries are both required",
            )
        )
    for entry in minio_entries:
        _check_minio_entry(entry, findings)
    dockerfile = (root / "infra/minio/Dockerfile").read_text(encoding="utf-8")
    if "not approved for production" not in dockerfile:
        findings.append(
            Finding(
                check="minio-production-policy",
                code="MINIO_PRODUCTION_GUARD_MISSING",
                path="infra/minio/Dockerfile",
                message=(
                    "MinIO image must retain an explicit production prohibition label"
                ),
            )
        )
    source_entry = next(
        (entry for entry in minio_entries if entry.name == "MinIO server source"),
        None,
    )
    local_entry = next(
        (entry for entry in minio_entries if entry.name == "MinIO local image"),
        None,
    )
    _check_minio_source_args(source_entry, dockerfile, findings)
    _check_minio_local_image(root, local_entry, findings)


def _directory_input_paths(root: Path, relative_directory: str) -> set[str]:
    directory = root / relative_directory
    if directory.is_symlink() or not directory.is_dir():
        raise AuditDataError(
            f"audited input directory is missing or a symlink: {relative_directory}"
        )
    members: set[str] = set()
    for candidate in directory.rglob("*"):
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_symlink():
            raise AuditDataError(f"audited input must not be a symlink: {relative}")
        if candidate.is_file():
            members.add(relative)
        elif not candidate.is_dir():
            raise AuditDataError(f"audited input is not a regular file: {relative}")
    if not members:
        raise AuditDataError(f"audited input directory is empty: {relative_directory}")
    return members


def _input_hashes(root: Path) -> tuple[tuple[str, str], ...]:
    paths = set(_EXPECTED_RELEASE_INPUT_FILES)
    paths.update(_AUDIT_POLICY_INPUT_FILES)
    input_directories: tuple[str, ...] = (
        *_EXPECTED_RELEASE_INPUT_DIRECTORIES,
        *_AUDIT_POLICY_INPUT_DIRECTORIES,
    )
    local_action_root = root / _OPTIONAL_LOCAL_ACTION_DIRECTORY
    if local_action_root.exists() or local_action_root.is_symlink():
        input_directories = (*input_directories, _OPTIONAL_LOCAL_ACTION_DIRECTORY)
    for relative_directory in input_directories:
        paths.update(_directory_input_paths(root, relative_directory))

    for relative in paths:
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise AuditDataError(
                f"audited input is missing or not a regular file: {relative}"
            )
    return tuple(
        (
            path,
            hashlib.sha256((root / path).read_bytes()).hexdigest(),
        )
        for path in sorted(paths)
    )


def audit(root: Path) -> AuditReport:
    """Run every offline dependency check against ``root``."""

    findings: list[Finding] = []
    entries: tuple[RegisterEntry, ...] = ()
    dependencies: list[DirectDependency] = []
    try:
        entries = load_register(root / "docs/dependencies.md")
        dependencies.extend(_discover_python(root, findings))
        dependencies.extend(_discover_npm(root, findings))
        dependencies.extend(_discover_github_actions(root, findings))
        _check_registration(entries, dependencies, findings)
        _check_github_action_metadata(root, entries, findings)
        _check_uv_lock(root, dependencies, findings)
        peers = _check_pnpm_lock(root, dependencies, findings)
        _check_typescript_eslint(dependencies, peers, findings)
        _check_containers(root, entries, findings)
        _check_tools(root, entries, findings)
        _check_minio_policy(root, entries, findings)
    except (AuditDataError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        findings.append(
            Finding(
                check="register-schema",
                code="AUDIT_INPUT_INVALID",
                path=".",
                message=str(error),
            )
        )

    sorted_dependencies = tuple(
        sorted(
            dependencies,
            key=lambda item: (item.kind, item.path, item.group, item.name),
        )
    )
    sorted_findings = tuple(
        sorted(
            findings,
            key=lambda item: (item.check, item.code, item.path, item.message),
        )
    )
    try:
        hashes = _input_hashes(root)
    except (AuditDataError, OSError) as error:
        hashes = ()
        sorted_findings += (
            Finding(
                check="register-schema",
                code="AUDIT_INPUT_MISSING",
                path=".",
                message=str(error),
            ),
        )
    return AuditReport(
        entries=entries,
        direct_dependencies=sorted_dependencies,
        findings=sorted_findings,
        input_hashes=hashes,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--write-evidence",
        action="store_true",
        help="write evidence/dependency-audit.json atomically",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="override evidence path (requires --write-evidence)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    arguments = _parser().parse_args(argv)
    root = arguments.root.resolve()
    report = audit(root)
    payload = report.to_json()
    if arguments.output is not None and not arguments.write_evidence:
        _parser().error("--output requires --write-evidence")
    if arguments.write_evidence:
        output = arguments.output or (root / "evidence/dependency-audit.json")
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8", newline="\n")
        temporary.replace(output)
    sys.stdout.write(payload)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
