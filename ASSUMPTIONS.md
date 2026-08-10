# Assumptions

Decisions made without user input are recorded here with the safest available
interpretation and the cheapest later verification.

## 2026-08-09 — Foundation runtime semantics

- **Decision:** Development readiness means that the checked-in service process
  is correctly configured and its declared dependencies are usable. It does not
  mean the methane-analysis workflow or production conditions in `GOAL.md` §5
  have been achieved.
- **Reasoning:** `GOAL.md` §0A requires semantic readiness while the repository
  is still at Tier 0; reporting domain readiness before the pipeline exists
  would be fabricated success.
- **Cheapest verification:** Inspect each `/livez` and `/readyz`
  contract and confirm the web surface displays `not yet in production` until
  all §5 evidence exists.

## 2026-08-09 — Local infrastructure

- **Decision:** Use repository-scoped Docker Compose for PostGIS and MinIO in
  local development, with `COMPOSE_PROJECT_NAME=gatewaygs-ai-4-earth-hackathon`
  and loopback-only published ports from 4170–4179.
- **Reasoning:** This matches the approved architecture and provides real
  persistence boundaries without modifying sibling repositories or shared
  namespaces.
- **Cheapest verification:** Run `docker compose --project-name
  gatewaygs-ai-4-earth-hackathon --env-file "$PWD/ports.env" --file
  "$PWD/compose.yaml" ps --all`, inspect every published address, and run `make
  dev:preflight` before and after lifecycle operations.

## 2026-08-09 — Python compatibility baseline

- **Decision:** Target CPython 3.13 for the initial locked toolchain rather than
  the host's default CPython 3.14.
- **Reasoning:** The approved geospatial and ML stack commonly lags the newest
  interpreter; 3.13 is installed locally and reduces native-wheel risk while
  remaining actively supported.
- **Cheapest verification:** Resolve the full lock, install on a clean 3.13
  environment, and exercise native imports in `verify-all`.

## 2026-08-09 — Python baseline superseded after registry verification

- **Supersedes:** The CPython 3.13 decision immediately above before it reached
  a committed release.
- **Decision:** Pin CPython 3.14.7 and require the 3.14 line.
- **Reasoning:** Primary-source verification found current macOS arm64 and Linux
  wheels for the approved native stack (including Rasterio and PyTorch), while
  CPython 3.14 retains regular binary bugfix support through October 2027. The
  original compatibility concern is therefore not supported by current data.
- **Cheapest verification:** `uv sync --frozen` on macOS arm64 and CI Linux,
  followed by native imports when those dependencies enter a working slice.

## 2026-08-09 — Local-only MinIO security boundary

- **Decision:** Build the last community MinIO security release from its exact
  AGPL source commit for loopback-only, synthetic local development. Do not use
  that build or its data in staging or production.
- **Reasoning:** The upstream community repository is archived and the final
  source release predates multiple 2026 high-severity fixes available only in
  maintained AIStor lines. `GOAL.md` §0A still requires the local MinIO boundary;
  source pinning is stronger than the older mutable Docker Hub image but cannot
  make it production-safe.
- **Cheapest verification:** Scan the built image, assert loopback-only Compose
  bindings, and require a maintained S3-compatible production adapter plus a
  new threat review before Tier 12.

## 2026-08-09 — PostGIS local architecture

- **Decision:** Pin the official `postgis/postgis:16-3.5-alpine` manifest and
  explicitly run `linux/amd64` under Docker emulation on Apple silicon.
- **Reasoning:** The official image currently publishes no arm64 runtime image.
  An explicit platform is deterministic and retains upstream provenance; silent
  emulation would distort later performance evidence.
- **Cheapest verification:** Record the container architecture and PostGIS
  version during `dev:health`. Performance evidence must use the declared
  production architecture, never this emulated local result.

## 2026-08-09 — TypeScript compatibility pin

- **Decision:** Pin TypeScript 6.0.3 even though registry `latest` is 7.0.2.
- **Reasoning:** The current strict `typescript-eslint` 8.66.0 peer range is
  `<6.1.0`; using TypeScript 7 would make the mandatory lint gate unsupported.
- **Cheapest verification:** Re-check the official peer range on every
  dependency upgrade and move to TypeScript 7 once the lint stack supports it.
