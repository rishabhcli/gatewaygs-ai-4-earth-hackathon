#!/usr/bin/env python3
"""Enforce dependency direction for present and future domain packages."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


# Domain packages are deliberately independent of application orchestration,
# network transports, persistence adapters, UI frameworks, and cloud SDK state.
FORBIDDEN_IMPORTS: dict[str, str] = {
    "apps": "application/UI layer",
    "cloud": "cloud/infrastructure layer",
    "infra": "infrastructure layer",
    "services": "service layer",
    "workers": "worker layer",
    "aioboto3": "cloud SDK",
    "azure": "cloud SDK",
    "boto3": "cloud SDK",
    "botocore": "cloud SDK",
    "google.cloud": "cloud SDK",
    "googleapiclient": "cloud SDK",
    "minio": "cloud/object-storage SDK",
    "aiohttp": "network transport",
    "asyncio": "process/network orchestration",
    "asyncio.subprocess": "process transport",
    "http.client": "network transport",
    "grpc": "network transport",
    "httpx": "network transport",
    "requests": "network transport",
    "socket": "network transport",
    "urllib3": "network transport",
    "urllib": "network transport",
    "websockets": "network transport",
    "multiprocessing": "process orchestration",
    "subprocess": "process orchestration",
    "asyncpg": "persistence adapter",
    "dbm": "persistence adapter",
    "psycopg": "persistence adapter",
    "pymongo": "persistence adapter",
    "redis": "persistence adapter",
    "shelve": "persistence adapter",
    "sqlite3": "persistence adapter",
    "sqlalchemy": "persistence framework",
    "celery": "worker framework",
    "django": "application framework",
    "fastapi": "application framework",
    "flask": "application framework",
    "starlette": "application framework",
    "uvicorn": "application framework",
    "dash": "UI framework",
    "gradio": "UI framework",
    "streamlit": "UI framework",
}

TIER0_EVIDENCE_KINDS: dict[str, str] = {
    "evidence/tier0-ci-run.json": "tier0-ci-run",
    "evidence/tier0-verify-all-output.json": "tier0-verify-all-output",
}
TIER0_STATIC_EVIDENCE = frozenset(
    {
        "evidence/README.md",
        "evidence/dependency-audit.json",
    }
)
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DOMAIN_PACKAGE_NAMES = frozenset({"retrieval", "simulation", "segmentation", "flux"})
MINIMUM_OWNERSHIP_DOCUMENT_CHARACTERS = 80
DYNAMIC_CODE_FUNCTIONS = frozenset({"compile", "eval", "exec"})


@dataclass(frozen=True, order=True)
class BoundaryViolation:
    path: str
    line: int
    column: int
    module: str
    category: str
    detail: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}:{self.column}: BND001 "
            f"domain import {self.module!r} crosses into {self.category}: {self.detail}"
        )


@dataclass(frozen=True, order=True)
class EvidencePolicyViolation:
    path: str
    detail: str

    def render(self) -> str:
        return f"{self.path}: EVD001 {self.detail}"


def forbidden_category(module: str) -> str | None:
    """Return the most-specific forbidden category for an absolute module."""

    matches = [
        (prefix, category)
        for prefix, category in FORBIDDEN_IMPORTS.items()
        if module == prefix or module.startswith(prefix + ".")
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: len(item[0]))[1]


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.violations: list[BoundaryViolation] = []
        self.importlib_aliases = {"importlib"}
        self.dynamic_import_names = {"__import__"}
        self.builtins_aliases: set[str] = set()
        self.dynamic_code_names = set(DYNAMIC_CODE_FUNCTIONS)

    def _record(self, node: ast.AST, module: str, detail: str) -> None:
        category = forbidden_category(module)
        if category is None:
            return
        self.violations.append(
            BoundaryViolation(
                path=self.relative_path,
                line=getattr(node, "lineno", 1),
                column=getattr(node, "col_offset", 0) + 1,
                module=module,
                category=category,
                detail=detail,
            )
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(node, alias.name, "absolute import")
            if alias.name == "importlib":
                self.importlib_aliases.add(alias.asname or alias.name)
            if alias.name == "builtins":
                self.builtins_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        # Relative imports stay within a domain package namespace. Absolute
        # imports are checked against repository and external adapter layers.
        if node.level == 0 and node.module is not None:
            if forbidden_category(node.module) is not None:
                self._record(node, node.module, "absolute from-import")
            else:
                for alias in node.names:
                    if alias.name != "*":
                        self._record(
                            node,
                            f"{node.module}.{alias.name}",
                            "absolute from-import",
                        )
        if node.level == 0 and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    self.dynamic_import_names.add(alias.asname or alias.name)
        if node.level == 0 and node.module == "builtins":
            for alias in node.names:
                if alias.name == "__import__":
                    self.dynamic_import_names.add(alias.asname or alias.name)
                if alias.name in DYNAMIC_CODE_FUNCTIONS:
                    self.dynamic_code_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    def _is_dynamic_import(self, function: ast.expr) -> bool:
        if isinstance(function, ast.Name):
            return function.id in self.dynamic_import_names
        return (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and (
                (
                    function.attr == "import_module"
                    and function.value.id in self.importlib_aliases
                )
                or (
                    function.attr == "__import__"
                    and function.value.id in self.builtins_aliases
                )
            )
        )

    def _is_dynamic_code(self, function: ast.expr) -> bool:
        if isinstance(function, ast.Name):
            return function.id in self.dynamic_code_names
        return (
            isinstance(function, ast.Attribute)
            and function.attr in DYNAMIC_CODE_FUNCTIONS
            and isinstance(function.value, ast.Name)
            and function.value.id in self.builtins_aliases
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        value = node.value
        if (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id in self.builtins_aliases
        ):
            aliases = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if value.attr == "__import__":
                self.dynamic_import_names.update(aliases)
            if value.attr in DYNAMIC_CODE_FUNCTIONS:
                self.dynamic_code_names.update(aliases)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self._is_dynamic_import(node.func):
            target = (
                node.args[0].value
                if node.args and isinstance(node.args[0], ast.Constant)
                else None
            )
            if not isinstance(target, str) or target.startswith("."):
                self.violations.append(
                    BoundaryViolation(
                        path=self.relative_path,
                        line=node.lineno,
                        column=node.col_offset + 1,
                        module="<dynamic>",
                        category="unverifiable dynamic dependency",
                        detail=(
                            "dynamic imports in domain packages require "
                            "a literal absolute target"
                        ),
                    )
                )
            else:
                self._record(node, target, "dynamic import")
        if self._is_dynamic_code(node.func):
            self.violations.append(
                BoundaryViolation(
                    path=self.relative_path,
                    line=node.lineno,
                    column=node.col_offset + 1,
                    module="<dynamic-code>",
                    category="unverifiable dynamic code",
                    detail="exec, eval, and compile are forbidden in domain packages",
                )
            )
        self.generic_visit(node)


def _validate_ownership_document(package_root: Path, name: str) -> None:
    ownership = package_root / "OWNERSHIP.md"
    if ownership.is_symlink() or not ownership.is_file():
        raise RuntimeError(f"packages/{name}/OWNERSHIP.md must be a regular file")
    try:
        ownership_text = ownership.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"packages/{name}/OWNERSHIP.md must be valid UTF-8") from exc
    expected_heading = f"# {name.capitalize()} ownership"
    if (
        not ownership_text.startswith(expected_heading + "\n")
        or len(ownership_text.strip()) < MINIMUM_OWNERSHIP_DOCUMENT_CHARACTERS
    ):
        raise RuntimeError(
            f"packages/{name}/OWNERSHIP.md must contain substantive ownership "
            f"text beginning with {expected_heading!r}"
        )


def _validate_domain_layout(packages_root: Path) -> None:
    if packages_root.is_symlink() or not packages_root.is_dir():
        raise RuntimeError("packages must be a real directory inside the repository")
    observed_directories = {
        path.name
        for path in packages_root.iterdir()
        if path.is_dir() or path.is_symlink()
    }
    if observed_directories != DOMAIN_PACKAGE_NAMES:
        missing = sorted(DOMAIN_PACKAGE_NAMES - observed_directories)
        unexpected = sorted(observed_directories - DOMAIN_PACKAGE_NAMES)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise RuntimeError(
            "domain package roots must be exactly retrieval, simulation, "
            "segmentation, and flux (" + "; ".join(details) + ")"
        )
    for name in sorted(DOMAIN_PACKAGE_NAMES):
        package_root = packages_root / name
        if package_root.is_symlink() or not package_root.is_dir():
            raise RuntimeError(f"packages/{name} must be a real directory")
        _validate_ownership_document(package_root, name)


def _python_files(packages_root: Path) -> Iterable[Path]:
    _validate_domain_layout(packages_root)
    return (
        path
        for path in sorted(packages_root.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def find_boundary_violations(root: Path) -> tuple[BoundaryViolation, ...]:
    """Scan only domain code that exists; planned empty directories are optional."""

    root = root.resolve(strict=True)
    packages_root = root / "packages"
    violations: list[BoundaryViolation] = []
    python_files = tuple(_python_files(packages_root))
    symlinks = {path for path in sorted(packages_root.rglob("*")) if path.is_symlink()}
    for path in sorted(symlinks):
        relative = path.relative_to(root).as_posix()
        violations.append(
            BoundaryViolation(
                path=relative,
                line=1,
                column=1,
                module="<symlink>",
                category="repository trust boundary",
                detail="domain package paths must not be symlinks",
            )
        )
    for path in python_files:
        if path in symlinks:
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(packages_root):
            raise RuntimeError("domain source path escaped packages/")
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (SyntaxError, UnicodeDecodeError) as exc:
            line = exc.lineno if isinstance(exc, SyntaxError) and exc.lineno else 1
            column = exc.offset if isinstance(exc, SyntaxError) and exc.offset else 1
            violations.append(
                BoundaryViolation(
                    path=relative,
                    line=line,
                    column=column,
                    module="<unparseable>",
                    category="boundary analysis failure",
                    detail="domain source must be valid UTF-8 Python",
                )
            )
            continue
        visitor = _ImportVisitor(relative)
        visitor.visit(tree)
        violations.extend(visitor.violations)
    return tuple(sorted(violations))


def _read_evidence_object(path: Path) -> tuple[dict[str, object] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, UnicodeDecodeError:
        return None, "foundational evidence must be valid UTF-8 JSON"
    if not isinstance(payload, dict):
        return None, "foundational evidence must be a JSON object"
    return payload, None


def _common_tier0_evidence_error(
    payload: dict[str, object], expected_kind: str
) -> str | None:
    inputs = payload.get("inputs")
    commit = inputs.get("git_commit") if isinstance(inputs, dict) else None
    versions = payload.get("tool_versions")
    valid_versions = (
        isinstance(versions, dict)
        and bool(versions)
        and all(
            isinstance(name, str) and name and isinstance(version, str) and version
            for name, version in versions.items()
        )
    )
    rules = (
        (
            type(payload.get("schema_version")) is int
            and payload.get("schema_version") == 1,
            "foundational evidence schema_version must be the integer 1",
        ),
        (
            payload.get("kind") == expected_kind,
            f"foundational evidence kind must be {expected_kind!r}",
        ),
        (
            payload.get("command") == "make verify-all",
            "foundational evidence command must be 'make verify-all'",
        ),
        (
            "seed" in payload and payload["seed"] is None,
            "deterministic foundational evidence seed must be null",
        ),
        (
            isinstance(commit, str)
            and GIT_COMMIT_PATTERN.fullmatch(commit) is not None,
            "foundational evidence inputs.git_commit must be a full commit SHA",
        ),
        (
            valid_versions,
            "foundational evidence tool_versions must be a non-empty string map",
        ),
    )
    return next((message for valid, message in rules if not valid), None)


def _ci_evidence_error(payload: dict[str, object]) -> str | None:
    run_url = payload.get("run_url")
    log = payload.get("output")
    valid_location = (
        isinstance(run_url, str)
        and run_url.startswith("https://github.com/")
        and "/actions/runs/" in run_url
    ) or (isinstance(log, str) and bool(log.strip()))
    rules = (
        (
            valid_location,
            "Tier 0 CI evidence must contain a GitHub run URL or non-empty log",
        ),
        (
            payload.get("conclusion") == "success",
            "Tier 0 CI evidence conclusion must be 'success'",
        ),
    )
    return next((message for valid, message in rules if not valid), None)


def _verify_all_evidence_error(payload: dict[str, object]) -> str | None:
    output = payload.get("output")
    invalid = (
        payload.get("clean_checkout") is not True
        or type(payload.get("exit_code")) is not int
        or payload.get("exit_code") != 0
        or not isinstance(output, str)
        or not output.strip()
    )
    return (
        "verify-all evidence must record clean-checkout exit 0 and output"
        if invalid
        else None
    )


def _typed_tier0_evidence_error(path: Path, expected_kind: str) -> str | None:
    payload, read_error = _read_evidence_object(path)
    if payload is None:
        return read_error
    common_error = _common_tier0_evidence_error(payload, expected_kind)
    if common_error is not None:
        return common_error
    if expected_kind == "tier0-ci-run":
        return _ci_evidence_error(payload)
    return _verify_all_evidence_error(payload)


def find_tier0_evidence_violations(
    root: Path,
) -> tuple[EvidencePolicyViolation, ...]:
    """Allow only non-domain Tier 0 evidence without a real evaluator."""

    root = root.resolve(strict=True)
    evidence_root = root / "evidence"
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise RuntimeError("evidence must be a real directory inside the repository")
    violations: list[EvidencePolicyViolation] = []
    for path in sorted(evidence_root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            violations.append(
                EvidencePolicyViolation(
                    path=relative,
                    detail="evidence paths must not be symlinks",
                )
            )
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            violations.append(
                EvidencePolicyViolation(
                    path=relative,
                    detail="evidence artifacts must be regular files",
                )
            )
            continue
        if relative in TIER0_STATIC_EVIDENCE:
            continue
        expected_kind = TIER0_EVIDENCE_KINDS.get(relative)
        if expected_kind is not None:
            detail = _typed_tier0_evidence_error(path, expected_kind)
            if detail is not None:
                violations.append(EvidencePolicyViolation(relative, detail))
            continue
        violations.append(
            EvidencePolicyViolation(
                path=relative,
                detail=(
                    "unregistered artifact requires a real domain evaluation runner"
                ),
            )
        )
    return tuple(sorted(violations))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--validate-tier0-evidence", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.validate_tier0_evidence:
        try:
            evidence_violations = find_tier0_evidence_violations(args.root)
        except (OSError, RuntimeError) as exc:
            print(f"EVAL ERROR: {exc}", file=sys.stderr)  # noqa: T201
            return 1
        if evidence_violations:
            for evidence_violation in evidence_violations:
                print(evidence_violation.render(), file=sys.stderr)  # noqa: T201
            print(  # noqa: T201
                "EVAL ERROR: evidence artifacts exist but no real evaluation "
                "runner is registered",
                file=sys.stderr,
            )
            return 1
        print(  # noqa: T201
            "EVAL OK: no domain metric artifacts are published at Tier 0"
        )
        return 0
    try:
        violations = find_boundary_violations(args.root)
    except (OSError, RuntimeError) as exc:
        print(f"BOUNDARY ERROR: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    if violations:
        for boundary_violation in violations:
            print(boundary_violation.render(), file=sys.stderr)  # noqa: T201
        print(  # noqa: T201
            f"BOUNDARY ERROR: {len(violations)} dependency violation(s)",
            file=sys.stderr,
        )
        return 1
    print("BOUNDARY OK: present domain packages depend only on allowed layers")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
