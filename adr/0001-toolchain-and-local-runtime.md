# ADR-0001: Toolchain and local runtime boundaries

- **Status:** Accepted for Tier 0; dependency versions remain lockfile-owned
- **Date:** 2026-08-09

## Context

The repository must support a Python geospatial/ML pipeline, FastAPI control
plane, React/MapLibre viewer, PostGIS catalog, and S3-compatible object storage.
It shares a machine and Docker daemon with fifteen sibling repositories, so
unscoped processes, default ports, and mutable global dependencies are unsafe.

## Options considered

1. A single Python environment plus ad-hoc npm commands and host-installed data
   services. This has the lowest initial setup cost but weak reproducibility and
   shared-host isolation.
2. One giant application container. This simplifies startup but collapses the
   API/worker/viewer ownership boundaries and makes local iteration expensive.
3. Locked Python and web workspaces with repository-scoped Docker Compose for
   stateful boundaries, orchestrated by a checked-in lifecycle command.

## Decision

Choose option 3.

- CPython 3.14.7 dependencies are resolved and installed with `uv` 0.12.3 from
  a locked `pyproject.toml`/`uv.lock` pair.
- The web workspace uses Node.js 24.19.0 LTS, pnpm 11.21.0, strict TypeScript,
  and the exact lock recorded by `package.json` and `pnpm-lock.yaml`.
- PostGIS and MinIO run as pinned Compose services under the project name
  `gatewaygs-ai-4-earth-hackathon`.
- Application services are separate processes and bind only the exclusive
  `4170–4179` block on `127.0.0.1`.
- A repository-owned lifecycle controller performs preflight, startup, semantic
  health, and ownership-checked shutdown. It never performs broad process or
  container operations.
- Docker Engine 24+ and Compose 2.24+ are capability-probed rather than assumed;
  the validated local snapshot is Engine 29.6.2 and Compose 5.3.1.
- Syft 1.49.0 generates normalized CycloneDX 1.7 inventories for both locked
  application dependencies and deployable container images. The release
  manifest hashes those inventories and every declared build input.

## Consequences

- Clean setup requires the exact uv, Node, pnpm, and Syft versions plus a Docker
  daemon/Compose implementation meeting the probed floors, but no global
  project packages.
- Native geospatial and ML dependencies remain outside Tier 0 until a vertical
  capability uses them; their addition requires an updated dependency review.
- The source-built MinIO service is restricted to loopback synthetic local
  development because upstream community maintenance ended before later
  high-severity fixes. Production requires a maintained S3-compatible adapter;
  local readiness is not evidence that this production boundary is resolved.
- Local readiness can be true while the product remains `not yet in production`;
  status copy and support claims must keep those states distinct.
- Docker image pin updates and language dependency upgrades are explicit,
  reviewable changes with regenerated evidence.

## Reversal

Replace the lifecycle adapters and lockfiles while preserving the port,
ownership, typed-config, and component-boundary contracts. A replacement must
demonstrate clean-checkout parity and scoped shutdown before this ADR is
superseded.
