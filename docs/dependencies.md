# Tier 0 dependency register

This is the canonical direct-dependency, tool, source, and container register for
the repository. It is a **point-in-time review completed 2026-08-10**, not a claim
that a pin can never become vulnerable. Manifests and lockfiles remain
authoritative for resolution; the JSON block is authoritative for review
metadata and is consumed directly by scripts/dependency_audit.py.

## Enforcement and evidence

Run from the repository root:

```sh
uv run --frozen --offline python scripts/dependency_audit.py --write-evidence
```

The command is offline-only by design: it reads fixed local manifests, never
reads environment values, never invokes a package manager, and never opens a
socket. It rejects unregistered or non-exact direct pins (including every external
GitHub Action), lock mismatches, unhashed lock artifacts, mutable external
container references, incompatible TypeScript/ESLint peer ranges, Syft/SBOM
policy drift, and any MinIO production approval. Stable output
is evidence/dependency-audit.json and includes the generating command,
`seed: null` (the audit contains no randomized step), and SHA-256 hashes of
every audited input, including the frozen release-manifest input surface.

Docker Engine 29.6.2 and Docker Compose 5.3.1 are the exact versions
validated on the 2026-08-09 Tier 0 host; they are observations, not portable
required pins. Supported hosts require Engine >=24.0.0 and Compose >=2.24.0,
a reachable daemon, and the repository config/build/lifecycle capability
probes. Python, Node, uv, pnpm, and Syft remain exact manifest-enforced tool pins.
All external GitHub Actions used by workflows or local composite actions are
immutable full-commit dependencies and must be registered; a new, tag-pinned,
or non-canonical flow-style `uses:` reference fails the offline audit.
GNU Make, Git, and lsof are direct host capabilities. Their exact validated
macOS snapshots are recorded below, while portable support uses the documented
minimum/capability probes and permits compatible host drift. `/bin/sh` and the
basic POSIX utilities used by recipes are the declared operating-system baseline,
not separately vendored dependencies.
The MinIO Dockerfile's Go 1.24.8 toolchain and its `wget`, `sha256sum`, and
`tar` commands are supplied by the digest-pinned build-base image and are image
transitives, not host prerequisites.

## Non-negotiable MinIO disposition

The local MinIO server is restricted to loopback-only synthetic development.
Its open-source repository is archived and its final release has known 2026
advisories without fixes on that source line. It is **not approved for
production**; the audit fails if either MinIO entry says otherwise. Production
object storage requires a maintained alternative and a new review.

## Machine-readable canonical register

Every entry includes exact version, purpose, licence, maintenance/currentness,
security history/current posture, native/binary implications, known cost or an
explicit measurement gap, update trigger, and primary sources.

<!-- dependency-register:start -->
```json
{
  "entries": [
    {
      "cost": "Production runtime; wheel/install and request overhead were not separately benchmarked.",
      "id": "python:fastapi",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "fastapi",
      "native_binary": "Pure Python; imports Starlette and Pydantic, whose pydantic-core wheel is native Rust.",
      "purpose": "Typed HTTP job-control and health API framework.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent. Historical GHSA-8h2j-cgx8-6xv7 affected old versions and is fixed in this pin.",
      "sources": [
        "https://pypi.org/project/fastapi/0.141.1/",
        "https://github.com/fastapi/fastapi/security/advisories/GHSA-8h2j-cgx8-6xv7"
      ],
      "update_trigger": "Upgrade on a published advisory, supported-runtime or protocol change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "0.141.1"
    },
    {
      "cost": "Production network runtime; independent latency and RSS have not been benchmarked.",
      "id": "python:httpx",
      "kind": "python",
      "license": "BSD-3-Clause",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "httpx",
      "native_binary": "Pure Python here; TLS behavior also depends on Python/OpenSSL and transitive packages.",
      "purpose": "Async HTTP client at external provider boundaries.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/httpx/0.28.1/",
        "https://github.com/encode/httpx"
      ],
      "update_trigger": "Upgrade on a published advisory, supported-runtime or protocol change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "0.28.1"
    },
    {
      "cost": "Production client runtime; network transfer dominates and is not yet benchmarked.",
      "id": "python:minio",
      "kind": "python",
      "license": "Apache-2.0",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "minio",
      "native_binary": "Pure Python client using urllib3 and Python crypto/hash primitives.",
      "purpose": "S3-compatible client adapter; this is not the MinIO server.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/minio/7.2.20/",
        "https://github.com/minio/minio-py"
      ],
      "update_trigger": "Upgrade on client advisory, S3 contract drift, or selection of the production object-store adapter.",
      "version": "7.2.20"
    },
    {
      "cost": "Production native wheel and DB connections; disk, RSS, and query costs are not yet benchmarked.",
      "id": "python:psycopg",
      "kind": "python",
      "license": "LGPL-3.0-only",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "psycopg",
      "native_binary": "The Python package requests psycopg-binary, which bundles native libpq/C code in platform wheels.",
      "purpose": "PostgreSQL/PostGIS catalog driver with the binary extra.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/psycopg/3.3.4/",
        "https://github.com/psycopg/psycopg"
      ],
      "update_trigger": "Upgrade immediately for libpq/psycopg advisories or supported-PostgreSQL changes.",
      "version": "3.3.4"
    },
    {
      "cost": "Production validation CPU/RSS and native wheel; per-model cost is not yet benchmarked.",
      "id": "python:pydantic",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "pydantic",
      "native_binary": "Uses the pydantic-core native Rust extension; source builds require Rust.",
      "purpose": "Runtime schemas and fail-closed trust-boundary validation.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent. Historical GHSA-5jqp-qgf6-3pvh affected old versions and is fixed in this pin.",
      "sources": [
        "https://pypi.org/project/pydantic/2.13.4/",
        "https://github.com/pydantic/pydantic/security/advisories/GHSA-5jqp-qgf6-3pvh"
      ],
      "update_trigger": "Upgrade on a published advisory, supported-runtime or protocol change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "2.13.4"
    },
    {
      "cost": "Startup-only parsing; exact startup cost is not separately benchmarked.",
      "id": "python:pydantic-settings",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "pydantic-settings",
      "native_binary": "Pure Python itself; inherits pydantic-core native code through Pydantic.",
      "purpose": "Typed startup configuration and refusal on invalid input.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/pydantic-settings/2.15.0/",
        "https://github.com/pydantic/pydantic-settings"
      ],
      "update_trigger": "Upgrade on a published advisory, supported-runtime or protocol change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "2.15.0"
    },
    {
      "cost": "Production server runtime; throughput and RSS have not yet been benchmarked.",
      "id": "python:uvicorn",
      "kind": "python",
      "license": "BSD-3-Clause",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "uvicorn",
      "native_binary": "Base pin is Python; optional uvloop/httptools native extras are not requested.",
      "purpose": "ASGI server for API and worker-health processes.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/uvicorn/0.52.1/",
        "https://github.com/Kludex/uvicorn"
      ],
      "update_trigger": "Upgrade on a published advisory, supported-runtime or protocol change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "0.52.1"
    },
    {
      "cost": "Production HTTP transport runtime and connection pools; network transfer dominates and independent RSS/latency are not yet benchmarked.",
      "id": "python:urllib3",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; 2.7.0 was the current stable release in the 2026-08-09 review.",
      "manifest": {
        "group": "project.dependencies",
        "path": "pyproject.toml"
      },
      "name": "urllib3",
      "native_binary": "Pure Python; TLS behavior depends on the CPython ssl module and linked OpenSSL.",
      "purpose": "Explicit HTTP transport exception contract for the MinIO client boundary.",
      "scope": "runtime",
      "security": "No advisory affecting 2.7.0 was reported by the official PyPI vulnerability surface in the 2026-08-09 review. urllib3 has historical request-routing, redirect, and decompression advisories in older lines; this is a point-in-time posture, not proof of absence.",
      "sources": [
        "https://pypi.org/project/urllib3/2.7.0/",
        "https://github.com/urllib3/urllib3/security"
      ],
      "update_trigger": "Upgrade immediately on urllib3 or Python/OpenSSL advisory, MinIO-client compatibility change, or quarterly review; regenerate uv.lock and run every Python gate.",
      "version": "2.7.0"
    },
    {
      "cost": "Test-only; case counts are explicit in tests rather than estimated here.",
      "id": "python:hypothesis",
      "kind": "python",
      "license": "MPL-2.0",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependency-groups.dev",
        "path": "pyproject.toml"
      },
      "name": "hypothesis",
      "native_binary": "Pure Python; generated cases can be CPU/RSS intensive but never ship.",
      "purpose": "Property-based and adversarial invariant testing.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/hypothesis/6.165.2/",
        "https://github.com/HypothesisWorks/hypothesis"
      ],
      "update_trigger": "Upgrade on a published advisory, Python support or plugin compatibility change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "6.165.2"
    },
    {
      "cost": "Developer/CI-only install and typecheck cost; no production runtime.",
      "id": "python:mypy",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependency-groups.dev",
        "path": "pyproject.toml"
      },
      "name": "mypy",
      "native_binary": "Published wheels contain mypyc-compiled native extensions.",
      "purpose": "Strict Python static type checking.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/mypy/2.3.0/",
        "https://github.com/python/mypy"
      ],
      "update_trigger": "Upgrade on a published advisory, Python support or plugin compatibility change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "2.3.0"
    },
    {
      "cost": "Developer/CI-only; suite duration belongs in verification evidence.",
      "id": "python:pytest",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependency-groups.dev",
        "path": "pyproject.toml"
      },
      "name": "pytest",
      "native_binary": "Pure Python runner; tested dependencies may load native code.",
      "purpose": "Python unit, integration, and contract test runner.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/pytest/9.1.1/",
        "https://github.com/pytest-dev/pytest"
      ],
      "update_trigger": "Upgrade on a published advisory, Python support or plugin compatibility change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "9.1.1"
    },
    {
      "cost": "Developer/CI-only; runtime is proportional to async tests.",
      "id": "python:pytest-asyncio",
      "kind": "python",
      "license": "Apache-2.0",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependency-groups.dev",
        "path": "pyproject.toml"
      },
      "name": "pytest-asyncio",
      "native_binary": "Pure Python plugin with no production artifact.",
      "purpose": "Strict asyncio lifecycle support for pytest.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/pytest-asyncio/1.4.0/",
        "https://github.com/pytest-dev/pytest-asyncio"
      ],
      "update_trigger": "Upgrade on a published advisory, Python support or plugin compatibility change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "1.4.0"
    },
    {
      "cost": "Developer/CI-only instrumentation overhead; no production cost.",
      "id": "python:pytest-cov",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependency-groups.dev",
        "path": "pyproject.toml"
      },
      "name": "pytest-cov",
      "native_binary": "Pure Python plugin; coverage.py may use its optional C tracer transitively.",
      "purpose": "Coverage enforcement for Python tests.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/pytest-cov/7.1.0/",
        "https://github.com/pytest-dev/pytest-cov"
      ],
      "update_trigger": "Upgrade on a published advisory, Python support or plugin compatibility change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "7.1.0"
    },
    {
      "cost": "Developer/CI-only native binary; no production or browser cost.",
      "id": "python:ruff",
      "kind": "python",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependency-groups.dev",
        "path": "pyproject.toml"
      },
      "name": "ruff",
      "native_binary": "Native Rust executable distributed as platform-specific wheels.",
      "purpose": "Python linting and deterministic formatting.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 PyPI and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://pypi.org/project/ruff/0.16.2/",
        "https://github.com/astral-sh/ruff"
      ],
      "update_trigger": "Upgrade on a published advisory, Python support or plugin compatibility change, or the quarterly dependency review; regenerate uv.lock and run every Python gate.",
      "version": "0.16.2"
    },
    {
      "cost": "Browser payload when imported; emitted WOFF2 bytes are not yet published.",
      "id": "npm:@fontsource-variable/ibm-plex-sans",
      "kind": "npm",
      "license": "OFL-1.1",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependencies",
        "path": "apps/web/package.json"
      },
      "name": "@fontsource-variable/ibm-plex-sans",
      "native_binary": "Static font assets; no native install step.",
      "purpose": "Primary interface font assets.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@fontsource-variable/ibm-plex-sans/v/5.3.0"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "5.3.0"
    },
    {
      "cost": "Browser payload when imported; emitted WOFF2 bytes are not yet published.",
      "id": "npm:@fontsource-variable/source-serif-4",
      "kind": "npm",
      "license": "OFL-1.1",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependencies",
        "path": "apps/web/package.json"
      },
      "name": "@fontsource-variable/source-serif-4",
      "native_binary": "Static font assets; no native install step.",
      "purpose": "Serif evidence/display font assets.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@fontsource-variable/source-serif-4/v/5.3.0"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "5.3.0"
    },
    {
      "cost": "Ships in browser bundle; exact gzip contribution is not yet published.",
      "id": "npm:react",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependencies",
        "path": "apps/web/package.json"
      },
      "name": "react",
      "native_binary": "JavaScript only; no native install binary.",
      "purpose": "Evidence-viewer component runtime.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/react/v/19.2.8"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "19.2.8"
    },
    {
      "cost": "Material browser payload; exact contribution is measured only by build evidence.",
      "id": "npm:react-dom",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependencies",
        "path": "apps/web/package.json"
      },
      "name": "react-dom",
      "native_binary": "JavaScript only; no native install binary.",
      "purpose": "React DOM rendering and hydration.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/react-dom/v/19.2.8"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "19.2.8"
    },
    {
      "cost": "Bundled where imported; validation CPU and bytes are not yet benchmarked.",
      "id": "npm:zod",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "dependencies",
        "path": "apps/web/package.json"
      },
      "name": "zod",
      "native_binary": "TypeScript/JavaScript only.",
      "purpose": "Runtime validation of viewer-facing contracts.",
      "scope": "runtime",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/zod/v/4.4.3"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "4.4.3"
    },
    {
      "cost": "Test-only page-injection time; absent from production bundle.",
      "id": "npm:@axe-core/playwright",
      "kind": "npm",
      "license": "MPL-2.0",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "@axe-core/playwright",
      "native_binary": "JavaScript wrapper injecting axe-core into a test browser.",
      "purpose": "Automated browser accessibility assertions.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@axe-core/playwright/v/4.12.1"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "4.12.1"
    },
    {
      "cost": "Lint-only install; absent from production bundle.",
      "id": "npm:@eslint/js",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "@eslint/js",
      "native_binary": "JavaScript only.",
      "purpose": "Official ESLint flat-config rule presets.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@eslint/js/v/10.0.1",
        "https://typescript-eslint.io/users/dependency-versions/"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "10.0.1"
    },
    {
      "cost": "Test-only; browser downloads can consume hundreds of MB and never ship.",
      "id": "npm:@playwright/test",
      "kind": "npm",
      "license": "Apache-2.0",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "@playwright/test",
      "native_binary": "Platform Playwright driver; separately installed browsers are native binaries.",
      "purpose": "End-to-end browser test runner.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@playwright/test/v/1.62.1"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "1.62.1"
    },
    {
      "cost": "Typecheck only; erased from emitted JavaScript.",
      "id": "npm:@types/node",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "@types/node",
      "native_binary": "Declaration files only.",
      "purpose": "Node API declarations for build/test config.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@types/node/v/26.2.0"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "26.2.0"
    },
    {
      "cost": "Typecheck only; erased from emitted JavaScript.",
      "id": "npm:@types/react",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "@types/react",
      "native_binary": "Declaration files only.",
      "purpose": "React TypeScript declarations.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@types/react/v/19.2.18"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "19.2.18"
    },
    {
      "cost": "Typecheck only; erased from emitted JavaScript.",
      "id": "npm:@types/react-dom",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "@types/react-dom",
      "native_binary": "Declaration files only.",
      "purpose": "React DOM TypeScript declarations.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@types/react-dom/v/19.2.4"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "19.2.4"
    },
    {
      "cost": "Build/dev-only CPU and install graph; no browser runtime package.",
      "id": "npm:@vitejs/plugin-react",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "@vitejs/plugin-react",
      "native_binary": "JavaScript/Babel graph; Vite may install native helpers.",
      "purpose": "React transform and Fast Refresh for Vite.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/@vitejs/plugin-react/v/6.0.5"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "6.0.5"
    },
    {
      "cost": "Developer/CI lint cost; absent from production bundle.",
      "id": "npm:eslint",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "eslint",
      "native_binary": "JavaScript CLI on native Node.",
      "purpose": "Warning-free JS/TS lint gate.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/eslint/v/10.8.1",
        "https://typescript-eslint.io/users/dependency-versions/"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "10.8.1"
    },
    {
      "cost": "Lint-only dependency graph; absent from production bundle.",
      "id": "npm:eslint-plugin-react-hooks",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "eslint-plugin-react-hooks",
      "native_binary": "JavaScript plugin and parser graph.",
      "purpose": "React Hooks correctness rules.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/eslint-plugin-react-hooks/v/7.1.1"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "7.1.1"
    },
    {
      "cost": "Lint-only; absent from production bundle.",
      "id": "npm:eslint-plugin-react-refresh",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "eslint-plugin-react-refresh",
      "native_binary": "JavaScript plugin only.",
      "purpose": "Validates safe Fast Refresh exports.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/eslint-plugin-react-refresh/v/0.5.3"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "0.5.3"
    },
    {
      "cost": "Developer/CI formatting cost; absent from production bundle.",
      "id": "npm:prettier",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "prettier",
      "native_binary": "JavaScript CLI on Node.",
      "purpose": "Deterministic web formatting gate.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/prettier/v/3.8.2"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "3.8.2"
    },
    {
      "cost": "Build/typecheck CPU and install only; compiler never ships.",
      "id": "npm:typescript",
      "kind": "npm",
      "license": "Apache-2.0",
      "maintenance": "Actively maintained. 6.0.3 is intentionally below 6.1 because typescript-eslint 8.66.0 supports >=4.8.4 <6.1.0; newer TypeScript 7.0.2 is incompatible with that peer contract.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "typescript",
      "native_binary": "JavaScript compiler on Node.",
      "purpose": "Strict TypeScript compiler and project references.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/typescript/v/6.0.3",
        "https://typescript-eslint.io/users/dependency-versions/"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "6.0.3"
    },
    {
      "cost": "Lint/type-analysis CPU and install graph; never ships.",
      "id": "npm:typescript-eslint",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained current major; upstream supports ESLint ^8.57, ^9, or ^10 and TypeScript >=4.8.4 <6.1.0.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "typescript-eslint",
      "native_binary": "JavaScript packages parsing through Node/TypeScript.",
      "purpose": "TypeScript parser and ESLint rules.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent.",
      "sources": [
        "https://www.npmjs.com/package/typescript-eslint/v/8.66.0",
        "https://typescript-eslint.io/users/dependency-versions/"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "8.66.0"
    },
    {
      "cost": "Build/dev native install and CPU; emitted assets are budgeted separately.",
      "id": "npm:vite",
      "kind": "npm",
      "license": "MIT",
      "maintenance": "Actively maintained; this exact release was current in the 2026-08-09 review.",
      "manifest": {
        "group": "devDependencies",
        "path": "apps/web/package.json"
      },
      "name": "vite",
      "native_binary": "Installs native Rolldown/esbuild/lightningcss helpers transitively.",
      "purpose": "Viewer dev server and production bundler.",
      "scope": "development",
      "security": "No advisory affecting this exact pin was identified in the 2026-08-09 npm and upstream GitHub advisory review. This is a point-in-time posture, not proof that vulnerabilities are absent. Vite has historical dev-server request/filesystem advisories; 8.2.1 was the current patched release at review and the server remains loopback-only.",
      "sources": [
        "https://www.npmjs.com/package/vite/v/8.2.1"
      ],
      "update_trigger": "Upgrade on an advisory, upstream support or peer-range change, or quarterly review; regenerate pnpm-lock.yaml and run every web gate.",
      "version": "8.2.1"
    },
    {
      "cost": "Interpreter install and production runtime; disk/RSS varies by platform.",
      "id": "tool:cpython",
      "kind": "tool",
      "license": "Python-2.0",
      "maintenance": "3.14.7 was the current 3.14 bugfix release; PEP 745 defines its lifecycle.",
      "manifest": {
        "group": "whole-file",
        "path": ".python-version"
      },
      "name": "CPython",
      "native_binary": "Native CPython linked to platform libc/OpenSSL.",
      "purpose": "Python application and audit runtime.",
      "scope": "runtime-and-development",
      "security": "Use patched official releases; a Python/OpenSSL advisory triggers immediate update.",
      "sources": [
        "https://www.python.org/downloads/release/python-3147/",
        "https://peps.python.org/pep-0745/"
      ],
      "update_trigger": "Any 3.14 security/bugfix release or lifecycle transition.",
      "version": "3.14.7"
    },
    {
      "cost": "Developer/CI binary/cache; no production application cost.",
      "id": "tool:uv",
      "kind": "tool",
      "license": "Apache-2.0 OR MIT",
      "maintenance": "Actively maintained; required-version is enforced before resolution.",
      "manifest": {
        "group": "tool.uv.required-version",
        "path": "pyproject.toml"
      },
      "name": "uv",
      "native_binary": "Native Rust executable per platform.",
      "purpose": "Hermetic Python resolution, sync, and command execution.",
      "scope": "development",
      "security": "No exact-pin advisory identified in the 2026-08-09 upstream review.",
      "sources": [
        "https://github.com/astral-sh/uv/releases/tag/0.12.3",
        "https://docs.astral.sh/uv/reference/settings/#required-version"
      ],
      "update_trigger": "uv advisory, lock-format change, or quarterly review.",
      "version": "0.12.3"
    },
    {
      "cost": "Developer/CI runtime and node_modules; not the browser runtime.",
      "id": "tool:node",
      "kind": "tool",
      "license": "MIT",
      "maintenance": "Node 24 LTS exact release and lifecycle reviewed from official sources.",
      "manifest": {
        "group": "whole-file",
        "path": ".node-version"
      },
      "name": "Node.js",
      "native_binary": "Native Node/V8 executable per platform.",
      "purpose": "LTS web build, lint, test, and dev runtime.",
      "scope": "development",
      "security": "Node/V8/OpenSSL advisories trigger immediate patch review.",
      "sources": [
        "https://nodejs.org/dist/index.json",
        "https://github.com/nodejs/Release/blob/main/schedule.json"
      ],
      "update_trigger": "Node 24 security patch, lifecycle change, or engine-peer change.",
      "version": "24.19.0"
    },
    {
      "cost": "Developer/CI global store and linking; no browser runtime cost.",
      "id": "tool:pnpm",
      "kind": "tool",
      "license": "MIT",
      "maintenance": "Actively maintained; packageManager and engines.pnpm pin 11.21.0.",
      "manifest": {
        "group": "packageManager",
        "path": "package.json"
      },
      "name": "pnpm",
      "native_binary": "JavaScript CLI on Node with platform link behavior.",
      "purpose": "Exact JS package manager and lock producer.",
      "scope": "development",
      "security": "No exact-pin advisory identified in the 2026-08-09 upstream review.",
      "sources": [
        "https://github.com/pnpm/pnpm/releases/tag/v11.21.0"
      ],
      "update_trigger": "pnpm advisory, lock-format change, or quarterly review.",
      "version": "11.21.0"
    },
    {
      "compatibility": "Supported host constraint: Docker Engine client and reachable daemon >=24.0.0; exact version 29.6.2 is the validated 2026-08-09 host, not a portable required pin.",
      "cost": "Large host/image/volume storage; no browser bundle cost.",
      "id": "tool:docker-engine",
      "kind": "tool",
      "license": "Apache-2.0 for Moby engine/CLI; Docker Desktop has separate terms",
      "maintenance": "29.6.2 is the exact validated Tier 0 host version. Supported environments may use Engine >=24.0.0 when the daemon and repository Compose capability probe pass; the binary is not vendored.",
      "manifest": {
        "group": "validated-host-version",
        "path": "docs/dependencies.md",
        "supported_floor": "24.0.0"
      },
      "name": "Docker Engine",
      "native_binary": "Native daemon/CLI and macOS VM/runtime.",
      "purpose": "Builds/runs isolated local containers.",
      "scope": "development-and-local-runtime",
      "security": "Daemon advisories and release notes must be reviewed before upgrades; the version floor is not a vulnerability-free claim.",
      "sources": [
        "https://docs.docker.com/engine/release-notes/29/"
      ],
      "update_trigger": "Docker security release, build/capability incompatibility, or deliberate change to the >=24.0.0 support floor; record the newly validated exact version.",
      "version": "29.6.2"
    },
    {
      "compatibility": "Supported host constraint: Docker Compose plugin >=2.24.0 plus successful repository config capability probe; exact version 5.3.1 is the validated 2026-08-09 host, not a portable required pin.",
      "cost": "Host orchestration cost; images are listed separately.",
      "id": "tool:docker-compose",
      "kind": "tool",
      "license": "Apache-2.0",
      "maintenance": "5.3.1 is the exact validated Tier 0 plugin version. Supported environments may use Compose >=2.24.0 when repository config/build/lifecycle capability probes pass; the plugin is not vendored.",
      "manifest": {
        "group": "validated-host-version",
        "path": "docs/dependencies.md",
        "supported_floor": "2.24.0"
      },
      "name": "Docker Compose",
      "native_binary": "Native Go plugin/CLI.",
      "purpose": "Runs repository-namespaced local services.",
      "scope": "development-and-local-runtime",
      "security": "Compose parser/orchestration advisories require review; the version floor is not a vulnerability-free claim.",
      "sources": [
        "https://github.com/docker/compose/releases/tag/v5.3.1"
      ],
      "update_trigger": "Compose advisory, schema/capability incompatibility, or deliberate change to the >=2.24.0 support floor; record the newly validated exact version.",
      "version": "5.3.1"
    },
    {
      "cost": "Development/CI orchestration only; process startup and runner time depend on invoked targets. No production or browser-bundle cost.",
      "id": "tool:gnu-make",
      "kind": "tool",
      "license": "GPL-3.0-or-later",
      "maintenance": "GNU Make is actively maintained upstream (current manual covers 4.4.1); the validated Apple host snapshot is legacy GNU Make 3.81. The repository deliberately supports GNU Make >=3.81 syntax rather than requiring this exact portable host version.",
      "manifest": {
        "group": "validated-host-version",
        "path": "docs/dependencies.md",
        "supported_floor": "3.81"
      },
      "name": "GNU Make",
      "native_binary": "Host-native executable that interprets Makefile recipes and launches /bin/sh commands with the current user privileges.",
      "purpose": "Top-level reproducible command contract for bootstrap, checks, lifecycle, SBOM generation, and release verification.",
      "scope": "development-and-ci",
      "security": "Makefiles execute arbitrary shell commands by design. GNU Make 3.81 is not current upstream and a version string cannot reveal vendor backports, so the supported posture is host-managed patching plus trusted committed Makefiles, review of every recipe change, and no execution from an untrusted checkout.",
      "sources": [
        "https://www.gnu.org/software/make/",
        "https://www.gnu.org/software/make/manual/",
        "https://ftp.gnu.org/gnu/make/"
      ],
      "update_trigger": "Revalidate on any GNU Make or host-OS security update, CI runner change, or Makefile feature requiring newer syntax. Raise the >=3.81 compatibility floor only with macOS and ubuntu CI evidence and update the support matrix/register together.",
      "version": "3.81"
    },
    {
      "cost": "Development lifecycle only; one bounded local metadata query per isolation preflight. No network, production runtime, or browser-bundle cost.",
      "id": "tool:git",
      "kind": "tool",
      "license": "GPL-2.0-only",
      "maintenance": "Actively maintained; Git 2.54.0 is the validated local snapshot, while compatible host drift is allowed. Support is capability-based on the ownership/worktree commands used by devctl rather than an exact portable pin.",
      "manifest": {
        "group": "validated-host-version",
        "path": "docs/dependencies.md",
        "supported_capability": "git -C <root> check-ignore --quiet .dev/probe"
      },
      "name": "Git",
      "native_binary": "Host-native executable. The supported path invokes a non-network check-ignore query against the fixed repository root and captures bounded output.",
      "purpose": "Fail closed unless repository-owned .dev runtime state is covered by the checkout ignore policy.",
      "scope": "development",
      "security": "Git documents that commands run against an untrusted .git directory can execute configured hooks or commands. devctl resolves Git from PATH but confines the invocation to check-ignore in the known project root; the checkout itself must be trusted. Apply host Git security updates even when the capability remains compatible.",
      "sources": [
        "https://git-scm.com/docs/git",
        "https://git-scm.com/docs/git-check-ignore",
        "https://github.com/git/git/blob/v2.54.0/COPYING"
      ],
      "update_trigger": "Revalidate on a Git security advisory, host/CI image change, PATH ownership change, or check-ignore behavior change. Compatible versions need no evidence rewrite unless the validated snapshot or supported capability changes.",
      "version": "2.54.0"
    },
    {
      "cost": "Development lifecycle only; bounded local TCP listener probes spawn one short process per configured port. No network traffic, production runtime, or browser-bundle cost.",
      "id": "tool:lsof",
      "kind": "tool",
      "license": "lsof",
      "maintenance": "Upstream remains maintained; lsof 4.91 is the validated Apple host snapshot and is older than current upstream. Support is capability-based on bounded TCP/listener field output, not an exact portable host pin.",
      "manifest": {
        "group": "validated-host-version",
        "path": "docs/dependencies.md",
        "supported_capability": "lsof -nP -iTCP:<port> -sTCP:LISTEN -Fpcn"
      },
      "name": "lsof",
      "native_binary": "Host-native executable coupled to operating-system process and socket APIs. devctl requests machine-readable PID/command/name fields and treats malformed, failed, or timed-out output as refusal.",
      "purpose": "Identify TCP listeners safely so lifecycle preflight never kills or commandeers a foreign process.",
      "scope": "development",
      "security": "The observed system binary is vendor-supplied and its version string does not expose downstream patches. lsof reads local process/socket metadata; devctl runs it without privilege escalation, bounds execution, parses only field output, and fails closed on absence or error. Apply host OS/upstream security updates.",
      "sources": [
        "https://github.com/lsof-org/lsof",
        "https://github.com/lsof-org/lsof/blob/master/COPYING",
        "https://github.com/lsof-org/lsof/security"
      ],
      "update_trigger": "Revalidate on an lsof or host-OS advisory, field-output/exit-status change, or supported-platform change. Compatible host versions are allowed; update the validated snapshot and evidence when the documented observation changes.",
      "version": "4.91"
    },
    {
      "cost": "Development/release only: one platform-specific binary download plus one filesystem scan and two image scans. No production or browser-bundle cost. The release generator bounds each command to 300 seconds and 64 MiB of captured output; scan CPU, memory, Docker-daemon, and disk cost is not yet benchmarked.",
      "id": "tool:syft",
      "kind": "tool",
      "license": "Apache-2.0",
      "maintenance": "Actively maintained; 1.49.0 was the current immutable release in the 2026-08-10 review. Upstream applies security updates only to its most recent release.",
      "manifest": {
        "cyclonedx_format": "JSON",
        "cyclonedx_schema": "http://cyclonedx.org/schema/bom-1.7.schema.json",
        "cyclonedx_spec_version": "1.7",
        "group": "download-syft",
        "installer_action": "anchore/sbom-action/download-syft@e22c389904149dbc22b58101806040fa8d37a610",
        "installer_action_version": "v0.24.0",
        "internal_schema_version": "16.1.10",
        "path": ".github/workflows/ci.yml",
        "release_manifest": "release-manifest.json",
        "sbom_outputs": "application-locks.cdx.json,minio-image.cdx.json,postgis-image.cdx.json",
        "scanned_images": "gatewaygs-ai-4-earth-hackathon/minio:RELEASE.2025-10-15T17-29-55Z,postgis/postgis:16-3.5-alpine@sha256:d2fe6296c8ed5b21b31a426f51b9176b4d89f80a0a380632a7a833d604951273"
      },
      "name": "Syft",
      "native_binary": "Platform-specific Go executable; the reviewed 1.49.0 binary reports internal SchemaVersion 16.1.10. CI downloads the runner-specific binary through the separately registered action.",
      "purpose": "Generate deterministic CycloneDX JSON 1.7 SBOMs for application locks, the locally built MinIO image, and the digest-pinned PostGIS runtime image, then feed the content-addressed release manifest.",
      "scope": "development-and-release",
      "security": "No advisory affecting 1.49.0 was identified in the 2026-08-10 official upstream review. Historical moderate GHSA-rjcw-vg7j-m9rc and GHSA-jp7v-3587-2956 were fixed before this pin. Upstream supports only the latest release and explicitly excludes deliberately malicious artifact completeness from its trust boundary, so scans are restricted to trusted repository/build inputs with bounded output and time.",
      "sources": [
        "https://github.com/anchore/syft/releases/tag/v1.49.0",
        "https://github.com/anchore/syft/blob/v1.49.0/LICENSE",
        "https://github.com/anchore/syft/security",
        "https://github.com/anchore/syft/security/advisories/GHSA-rjcw-vg7j-m9rc",
        "https://github.com/anchore/syft/security/advisories/GHSA-jp7v-3587-2956",
        "https://github.com/anchore/sbom-action/tree/e22c389904149dbc22b58101806040fa8d37a610/download-syft",
        "https://github.com/anchore/sbom-action/releases/tag/v0.24.0",
        "https://cyclonedx.org/schema/bom-1.7.schema.json"
      ],
      "update_trigger": "Upgrade immediately for a Syft advisory because upstream supports only the latest release, or when cataloger, CycloneDX/internal schema, MinIO, or PostGIS image behavior changes. Update Makefile, CI action commit and syft-version, generator constants/tests, this register, SBOMs, and dependency evidence atomically.",
      "version": "1.49.0"
    },
    {
      "cost": "CI-only checkout network, Git process, workspace disk, and runner minutes; no production or browser-bundle cost.",
      "id": "github-action:actions-checkout",
      "kind": "github-action",
      "license": "MIT",
      "maintenance": "Actively maintained; the exact immutable v4 line commit was reviewed on 2026-08-10. It is not trusted through a mutable tag.",
      "manifest": {
        "group": "workflow.uses",
        "path": ".github/workflows/ci.yml",
        "reference": "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "release_line": "v4"
      },
      "name": "actions/checkout",
      "native_binary": "JavaScript/Node action invoking Git on the hosted runner; it writes the workspace and can configure credentials. persist-credentials is explicitly false.",
      "purpose": "Check out the exact repository revision for the frozen CI verification job without persisting the workflow token.",
      "scope": "ci",
      "security": "No published repository security advisory was present in the 2026-08-10 official review. The action executes before project tests with repository and runner access; a full commit pin limits tag substitution, and persist-credentials: false limits retained token exposure.",
      "sources": [
        "https://github.com/actions/checkout/tree/11d5960a326750d5838078e36cf38b85af677262",
        "https://github.com/actions/checkout/blob/11d5960a326750d5838078e36cf38b85af677262/LICENSE",
        "https://github.com/actions/checkout/security"
      ],
      "update_trigger": "Review on any checkout or Git advisory, runner-image/Node-runtime change, or quarterly CI dependency review; inspect the exact diff, replace the commit and release-line annotation together, then regenerate dependency evidence.",
      "version": "11d5960a326750d5838078e36cf38b85af677262"
    },
    {
      "cost": "CI-only runtime download/toolcache disk and runner minutes; no production or browser-bundle cost.",
      "id": "github-action:actions-setup-python",
      "kind": "github-action",
      "license": "MIT",
      "maintenance": "Actively maintained; the exact immutable v6 line commit was reviewed on 2026-08-10. It is not trusted through a mutable tag.",
      "manifest": {
        "group": "workflow.uses",
        "path": ".github/workflows/ci.yml",
        "reference": "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1",
        "release_line": "v6"
      },
      "name": "actions/setup-python",
      "native_binary": "JavaScript/Node action that resolves/downloads a platform-specific CPython toolcache payload and modifies the runner PATH.",
      "purpose": "Install and select the exact CPython 3.14.7 runtime used by CI.",
      "scope": "ci",
      "security": "No published repository security advisory was present in the 2026-08-10 official review. It downloads and activates native interpreter artifacts, so the action commit and requested Python version are both exact and check-latest is disabled.",
      "sources": [
        "https://github.com/actions/setup-python/tree/ece7cb06caefa5fff74198d8649806c4678c61a1",
        "https://github.com/actions/setup-python/blob/ece7cb06caefa5fff74198d8649806c4678c61a1/LICENSE",
        "https://github.com/actions/setup-python/security"
      ],
      "update_trigger": "Review on an action, CPython, toolcache, or runner advisory/change; update the action commit and release-line annotation while retaining the exact Python pin, then rerun all Python gates and regenerate evidence.",
      "version": "ece7cb06caefa5fff74198d8649806c4678c61a1"
    },
    {
      "cost": "CI-only binary download, tool installation, and runner minutes; no production or browser-bundle cost.",
      "id": "github-action:astral-sh-setup-uv",
      "kind": "github-action",
      "license": "MIT",
      "maintenance": "Actively maintained; the exact immutable v7 line commit was reviewed on 2026-08-10. It is not trusted through a mutable tag.",
      "manifest": {
        "group": "workflow.uses",
        "path": ".github/workflows/ci.yml",
        "reference": "astral-sh/setup-uv@94527f2e458b27549849d47d273a16bec83a01e9",
        "release_line": "v7"
      },
      "name": "astral-sh/setup-uv",
      "native_binary": "JavaScript/Node action that downloads the platform-specific native Rust uv executable and adds it to PATH; action-managed caching is disabled.",
      "purpose": "Install the exact uv 0.12.3 dependency manager used by the frozen CI contract.",
      "scope": "ci",
      "security": "No published repository security advisory was present in the 2026-08-10 official review. The action downloads an executable, so both the action commit and uv version are exact, and enable-cache is false to avoid a second implicit cache policy.",
      "sources": [
        "https://github.com/astral-sh/setup-uv/tree/94527f2e458b27549849d47d273a16bec83a01e9",
        "https://github.com/astral-sh/setup-uv/blob/94527f2e458b27549849d47d273a16bec83a01e9/LICENSE",
        "https://github.com/astral-sh/setup-uv/security"
      ],
      "update_trigger": "Review on an action or uv advisory/release, runner change, or quarterly CI review; inspect the exact action diff and update its commit plus the repository-wide uv pin and evidence together.",
      "version": "94527f2e458b27549849d47d273a16bec83a01e9"
    },
    {
      "cost": "CI-only package-manager download/install and runner minutes; project install/store cost is accounted separately; no browser-bundle cost.",
      "id": "github-action:pnpm-action-setup",
      "kind": "github-action",
      "license": "MIT",
      "maintenance": "Actively maintained; the exact immutable v4 line commit was reviewed on 2026-08-10. It is not trusted through a mutable tag.",
      "manifest": {
        "group": "workflow.uses",
        "path": ".github/workflows/ci.yml",
        "reference": "pnpm/action-setup@f40ffcd9367d9f12939873eb1018b921a783ffaa",
        "release_line": "v4"
      },
      "name": "pnpm/action-setup",
      "native_binary": "JavaScript/Node action that installs the pnpm CLI and modifies PATH; pnpm itself is JavaScript and invokes platform tooling during package installation.",
      "purpose": "Install the exact pnpm 11.21.0 package manager without implicitly installing project dependencies.",
      "scope": "ci",
      "security": "No published repository security advisory was present in the 2026-08-10 official review. It installs executable package-manager code, so the action commit and pnpm version are exact and run_install is false.",
      "sources": [
        "https://github.com/pnpm/action-setup/tree/f40ffcd9367d9f12939873eb1018b921a783ffaa",
        "https://github.com/pnpm/action-setup/blob/f40ffcd9367d9f12939873eb1018b921a783ffaa/LICENSE.md",
        "https://github.com/pnpm/action-setup/security"
      ],
      "update_trigger": "Review on an action or pnpm advisory/release, Corepack/Node compatibility change, or quarterly CI review; update the exact commit and repository pnpm pins atomically, then regenerate the lock/evidence.",
      "version": "f40ffcd9367d9f12939873eb1018b921a783ffaa"
    },
    {
      "cost": "CI-only runtime download/toolcache disk and runner minutes; no production or browser-bundle cost.",
      "id": "github-action:actions-setup-node",
      "kind": "github-action",
      "license": "MIT",
      "maintenance": "Actively maintained; the exact immutable v5 line commit was reviewed on 2026-08-10. It is not trusted through a mutable tag.",
      "manifest": {
        "group": "workflow.uses",
        "path": ".github/workflows/ci.yml",
        "reference": "actions/setup-node@a0853c24544627f65ddf259abe73b1d18a591444",
        "release_line": "v5"
      },
      "name": "actions/setup-node",
      "native_binary": "JavaScript/Node action that resolves/downloads a platform-specific Node.js executable/toolcache and changes PATH.",
      "purpose": "Install and select the exact Node.js 24.19.0 runtime used by frontend CI.",
      "scope": "ci",
      "security": "No published repository security advisory was present in the 2026-08-10 official review. It activates a native runtime, so the action commit and Node version are exact and check-latest is disabled.",
      "sources": [
        "https://github.com/actions/setup-node/tree/a0853c24544627f65ddf259abe73b1d18a591444",
        "https://github.com/actions/setup-node/blob/a0853c24544627f65ddf259abe73b1d18a591444/LICENSE",
        "https://github.com/actions/setup-node/security"
      ],
      "update_trigger": "Review on an action, Node.js, toolcache, or runner advisory/change; update the exact action commit and repository Node pin compatibly, rerun frontend/browser gates, and regenerate evidence.",
      "version": "a0853c24544627f65ddf259abe73b1d18a591444"
    },
    {
      "cost": "CI-only action and native binary download plus runner disk/minutes; subsequent scan cost is recorded on the Syft tool entry.",
      "id": "github-action:anchore-sbom-action-download-syft",
      "kind": "github-action",
      "license": "Apache-2.0",
      "maintenance": "Actively maintained; the exact immutable v0.24.0 line commit was reviewed on 2026-08-10. It is not trusted through a mutable tag.",
      "manifest": {
        "group": "workflow.uses",
        "path": ".github/workflows/ci.yml",
        "reference": "anchore/sbom-action/download-syft@e22c389904149dbc22b58101806040fa8d37a610",
        "release_line": "v0.24.0"
      },
      "name": "anchore/sbom-action/download-syft",
      "native_binary": "Composite/JavaScript action that downloads a platform-specific Go Syft executable and exposes it on PATH.",
      "purpose": "Download the exact Syft 1.49.0 executable used by the CI SBOM/release gate.",
      "scope": "ci",
      "security": "No published sbom-action repository advisory was present in the 2026-08-10 official review. This action installs executable scanner code before release checks, so both its commit and Syft version are exact; Syft advisories and trust limits are tracked separately on tool:syft.",
      "sources": [
        "https://github.com/anchore/sbom-action/tree/e22c389904149dbc22b58101806040fa8d37a610",
        "https://github.com/anchore/sbom-action/blob/e22c389904149dbc22b58101806040fa8d37a610/LICENSE",
        "https://github.com/anchore/sbom-action/security"
      ],
      "update_trigger": "Review with every Syft/action release or advisory; inspect the exact action diff and update its commit/release annotation, syft-version, Makefile/generator policy, SBOMs, register, and evidence atomically.",
      "version": "e22c389904149dbc22b58101806040fa8d37a610"
    },
    {
      "cost": "CI-only cache transfer/storage, archive CPU, workspace disk, and runner minutes; no production or browser-bundle cost.",
      "id": "github-action:actions-cache",
      "kind": "github-action",
      "license": "MIT",
      "maintenance": "Actively maintained; the exact immutable v4.3.0 line commit was reviewed on 2026-08-10. It is not trusted through a mutable tag.",
      "manifest": {
        "group": "workflow.uses",
        "path": ".github/workflows/ci.yml",
        "reference": "actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830",
        "release_line": "v4.3.0"
      },
      "name": "actions/cache",
      "native_binary": "JavaScript/Node action invoking archive/compression tooling and reading/writing runner filesystem paths; restored bytes can influence later installs.",
      "purpose": "Restore and save repository-owned uv, pnpm-store, and Playwright caches under a lockfile- and platform-qualified key.",
      "scope": "ci",
      "security": "No published repository security advisory was present in the 2026-08-10 official review. Cache contents are untrusted build inputs; the action is commit-pinned, paths are limited to .dev/cache, the key includes OS/architecture/tool pins/lock hashes, and no credentials are cached.",
      "sources": [
        "https://github.com/actions/cache/tree/0057852bfaa89a56745cba8c7296529d2fc39830",
        "https://github.com/actions/cache/blob/0057852bfaa89a56745cba8c7296529d2fc39830/LICENSE",
        "https://github.com/actions/cache/security"
      ],
      "update_trigger": "Review on an action/cache-service, archive, or runner advisory/change and quarterly; inspect the exact diff, retain bounded non-secret paths and content-qualified keys, update commit/release annotation, and regenerate evidence.",
      "version": "0057852bfaa89a56745cba8c7296529d2fc39830"
    },
    {
      "cost": "Build-only pull/cache; exact bytes not recorded.",
      "id": "container:dockerfile-frontend",
      "kind": "container",
      "license": "Apache-2.0",
      "maintenance": "Active frontend line; tag and digest are pinned.",
      "manifest": {
        "group": "syntax",
        "path": "infra/minio/Dockerfile",
        "reference": "docker/dockerfile:1.18@sha256:dabfc0969b935b2080555ace70ee69a5261af8a8f1b4df97b9e7fbcf6722eddf"
      },
      "name": "Dockerfile frontend",
      "native_binary": "Linux image executed only by BuildKit.",
      "purpose": "Immutable BuildKit Dockerfile parser frontend.",
      "scope": "build",
      "security": "No exact-digest advisory identified; digest changes require review.",
      "sources": [
        "https://github.com/moby/buildkit/tree/master/frontend/dockerfile"
      ],
      "update_trigger": "BuildKit advisory, required syntax feature, or reviewed digest refresh.",
      "version": "1.18"
    },
    {
      "cost": "Large build-only image/module cache; absent from runtime.",
      "id": "container:minio-build-base",
      "kind": "container",
      "license": "BSD-3-Clause for Go plus Alpine/package licences",
      "maintenance": "Digest-pinned legacy Go required by archived MinIO; outside the current two-release support window and build-only.",
      "manifest": {
        "group": "FROM build",
        "path": "infra/minio/Dockerfile",
        "reference": "golang:1.24.8-alpine3.22@sha256:3d78beb141d98f42337f1252ecf2a5f20374109929a4c3f6817f9e4179cc0ae5"
      },
      "name": "Go Alpine build image",
      "native_binary": "Linux toolchain emits a static CGO-disabled Go binary.",
      "purpose": "Compiles the exact MinIO source with its declared toolchain.",
      "scope": "build",
      "security": "No vulnerability-free claim; any toolchain advisory reopens removal.",
      "sources": [
        "https://go.dev/doc/devel/release",
        "https://hub.docker.com/_/golang"
      ],
      "update_trigger": "Any Go/Alpine advisory, toolchain requirement change, or MinIO removal.",
      "version": "Go 1.24.8 on Alpine 3.22"
    },
    {
      "cost": "Small base plus static server; compressed/RSS cost not benchmarked.",
      "id": "container:minio-runtime-base",
      "kind": "container",
      "license": "MIT for Alpine infrastructure plus package licences",
      "maintenance": "Alpine 3.22 is supported, but exact patch 3.22.1 is retained only for restricted local use.",
      "manifest": {
        "group": "FROM runtime",
        "path": "infra/minio/Dockerfile",
        "reference": "alpine:3.22.1@sha256:4bcff63911fcb4448bd4fdacec207030997caf25e9bea4045fa6c8c44de311d1"
      },
      "name": "Alpine MinIO runtime base",
      "native_binary": "musl Linux userspace; glibc-only binaries are incompatible.",
      "purpose": "Minimal CA/user/filesystem base for local MinIO.",
      "scope": "local-development-runtime",
      "security": "Digest prevents drift, not OS CVEs; review every update and never promote.",
      "sources": [
        "https://alpinelinux.org/releases/"
      ],
      "update_trigger": "Alpine advisory/digest change, CA update, or MinIO removal.",
      "version": "3.22.1"
    },
    {
      "cost": "Large persistent DB/geospatial image and volume; budgets not measured.",
      "id": "container:postgis",
      "kind": "container",
      "license": "MIT scripts, PostgreSQL, GPL-2.0-or-later PostGIS, plus package licences",
      "maintenance": "Maintained 16-3.5 Alpine line; 2026-06-19 matrix reports amd64, PostgreSQL 16.14, PostGIS 3.5.7, Alpine 3.24; PostgreSQL 16 supported through 2028-11.",
      "manifest": {
        "group": "service:catalog",
        "path": "compose.yaml",
        "reference": "postgis/postgis:16-3.5-alpine@sha256:d2fe6296c8ed5b21b31a426f51b9176b4d89f80a0a380632a7a833d604951273"
      },
      "name": "PostGIS catalog image",
      "native_binary": "Explicit linux/amd64 native geospatial stack, emulated on Apple Silicon.",
      "purpose": "Local production-shaped PostGIS metadata catalog.",
      "scope": "local-development-runtime",
      "security": "Immutable digest but no all-package vulnerability-free claim; scan/review before updates.",
      "sources": [
        "https://github.com/postgis/docker-postgis#versions-2026-06-19",
        "https://www.postgresql.org/support/versioning/"
      ],
      "update_trigger": "PostgreSQL/PostGIS/Alpine advisory, supported-minor, architecture need, or quarterly review.",
      "version": "PostgreSQL 16.14 / PostGIS 3.5.7 / Alpine 3.24"
    },
    {
      "cost": "Cold source fetch, substantial binary and server CPU/RSS; no benchmark published.",
      "id": "source:minio-server",
      "kind": "source",
      "known_advisories": [
        "GHSA-hv4r-mvr4-25vw",
        "GHSA-9c4q-hq6p-c237",
        "GHSA-xh8f-g2qw-gcm7",
        "GHSA-h749-fxx7-pwpg",
        "GHSA-3rh2-v3gr-35p9",
        "GHSA-jv87-32hw-hh99",
        "GHSA-5cx5-wh4m-82fh"
      ],
      "license": "AGPL-3.0-or-later",
      "maintenance": "Upstream was archived read-only on 2026-04-25; final open-source line is unmaintained.",
      "manifest": {
        "commit": "9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a",
        "group": "MINIO source ARGs",
        "path": "infra/minio/Dockerfile",
        "source_sha256": "45521908307306e925c98d629e1c17d78c8b72b6ee242b1bfb1409f7d8ee5841"
      },
      "name": "MinIO server source",
      "native_binary": "Go source compiled CGO-disabled into a static Linux binary.",
      "production_approved": false,
      "purpose": "Exact archived source for reproducible synthetic-development object storage.",
      "scope": "loopback-synthetic-local-development-only",
      "security": "The final open-source release is affected by published 2026 advisories including unauthenticated write, path traversal, denial of service, replication-header injection, LDAP enumeration/rate-limit, and OIDC algorithm-confusion issues. It is unmaintained and not production-approved. The tag fixed historical GHSA-jjjj-jwhf-8rgr, but later fixes are available only in AIStor.",
      "sources": [
        "https://github.com/minio/minio#readme",
        "https://github.com/minio/minio/releases/tag/RELEASE.2025-10-15T17-29-55Z",
        "https://github.com/minio/minio/security"
      ],
      "update_trigger": "Any non-loopback/production proposal must replace it; every new advisory reopens removal.",
      "version": "RELEASE.2025-10-15T17-29-55Z"
    },
    {
      "cost": "Local image, persistent volume, two loopback ports, CPU/RSS; budgets not measured.",
      "id": "container:minio-local",
      "kind": "container",
      "known_advisories": [
        "GHSA-hv4r-mvr4-25vw",
        "GHSA-9c4q-hq6p-c237",
        "GHSA-xh8f-g2qw-gcm7",
        "GHSA-h749-fxx7-pwpg",
        "GHSA-3rh2-v3gr-35p9",
        "GHSA-jv87-32hw-hh99",
        "GHSA-5cx5-wh4m-82fh"
      ],
      "license": "AGPL-3.0-or-later plus Alpine package licences",
      "maintenance": "Deterministic build from archived source; never an approved production container.",
      "manifest": {
        "group": "service:minio local build output",
        "local_build": "true",
        "path": "compose.yaml",
        "reference": "gatewaygs-ai-4-earth-hackathon/minio:RELEASE.2025-10-15T17-29-55Z"
      },
      "name": "MinIO local image",
      "native_binary": "Static Go server in musl Linux; non-root/read-only except data/tmp.",
      "production_approved": false,
      "purpose": "Locally built object storage for synthetic development and contract tests only.",
      "scope": "loopback-synthetic-local-development-only",
      "security": "The final open-source release is affected by published 2026 advisories including unauthenticated write, path traversal, denial of service, replication-header injection, LDAP enumeration/rate-limit, and OIDC algorithm-confusion issues. It is unmaintained and not production-approved. The tag fixed historical GHSA-jjjj-jwhf-8rgr, but later fixes are available only in AIStor.",
      "sources": [
        "https://github.com/minio/minio#readme",
        "https://github.com/minio/minio/security"
      ],
      "update_trigger": "Any production proposal fails audit; replace with a maintained approved store.",
      "version": "RELEASE.2025-10-15T17-29-55Z+9e49d5e7a648"
    }
  ],
  "reviewed_on": "2026-08-09",
  "schema_version": 1
}
```
<!-- dependency-register:end -->
