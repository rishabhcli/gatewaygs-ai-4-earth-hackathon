# Progress journal

This file is append-only. Each entry records a verified unit of work, the
commands and evidence behind it, and the next item selected by `GOAL.md` §10.1.


## 2026-08-10 — Tier 0 local lifecycle and honest foundation surface

- **Behaviour delivered:** Added the repository-owned `4170`–`4179` lifecycle
  with exact port/config validation, real PID start identities, scoped foreground
  launchers, loopback-only application and Compose listeners, generated local
  `0600` secrets, semantic PostGIS/PostGIS-extension and object-bucket probes,
  typed API/worker/asset readiness, and a web surface that reports
  `not yet in production` and refuses analysis intake.
- **Commands run:** `make dev:preflight`; `make dev:up`; `make dev:health`;
  `uv run --frozen pytest`; focused Ruff and strict-mypy commands over runtime
  and lifecycle code; `pnpm --dir apps/web run lint`; `pnpm --dir apps/web run
  typecheck`; and the Chromium Playwright accessibility/state suite.
- **Evidence:** The literal Make sequence returned readiness for PostGIS `4175`,
  MinIO API/console `4176`/`4177`, API `4170`, worker health `4172`, asset server
  `4173`, and web `4171`. A scoped shutdown/restart drill left every block port
  free before the restart. Lifecycle/runtime coverage reached 235 passing tests
  and 91.33% aggregate branch-plus-statement coverage before the subsequent
  release-manifest additions; the configured repository threshold remains 85%.
  Three Chromium E2E checks passed for truthful product state, keyboard skip
  navigation, and automated accessibility scanning. These are local foundation
  facts, not methane-analysis or production evidence.
- **Risks and limitations:** The source-pinned community MinIO build is approved
  only for loopback synthetic development and remains prohibited in production.
  Official PostGIS runs as explicit `linux/amd64` emulation on this Apple-silicon
  host, so its timings are not performance evidence. Independent Tier 0 audit
  findings and the full clean-checkout `verify-all` gate are still being closed;
  no domain result or metric exists.
- **Migration and rollback:** Local state is isolated in the exact Compose
  project and prefixed volumes. `make dev:down` signals only recorded launchers,
  whose wrappers stop only their allowlisted Compose service; a rollback of this
  foundation is the same scoped shutdown plus reversal of its coherent commit,
  without touching sibling repositories or foreign processes.
- **Blocked items:** None external. No paid service or credential is required for
  this unit.
- **Next item selected by `GOAL.md` §10.1:** Close every remaining Tier 0 release
  gate finding, regenerate the dependency/SBOM evidence, run `make verify-all`
  from a clean checkout, and then begin Tier 1 invariant encodings immediately.

## 2026-08-10 — Verified repository-wide status and next-agent handoff

- **Snapshot basis:** Audited clean `main` at commit `3dcefae8`, including every
  tracked file, the authoritative documents, local command surfaces, and
  [CI run 31402715746](https://github.com/rishabhcli/gatewaygs-ai-4-earth-hackathon/actions/runs/31402715746).
  This entry records current evidence; the earlier green lifecycle and test
  results above remain historical evidence and must not be read as the current
  gate state.
- **Honest position against the end goal:** The repository has a substantial
  Tier 0 foundation, but Tier 0 has **not exited**. No Tier 1 invariant has its
  complete machine-enforcement/property/fault/alert evidence, and the hard
  methane-analysis core has not started. Production has not occurred under any
  defensible reading of `GOAL.md` §5.

### What is implemented now

- Exact Python, Node, uv, pnpm, JavaScript, and container dependency pins;
  frozen language lockfiles; a direct-dependency register; and commands for
  formatting, linting, typing, tests, integration, E2E, evaluation, build,
  SBOM, and full verification.
- Repository-owned local lifecycle code for ports `4170`–`4179`, scoped PID and
  Compose ownership, generated mode-`0600` development secrets, loopback-only
  PostGIS/MinIO, typed configuration, semantic liveness/readiness, bounded
  dependency probes, structured redacted request logs, and correlation IDs.
- A FastAPI foundation exposes health and an explicit
  `PIPELINE_NOT_IMPLEMENTED` product state. It deliberately has no analysis-job
  intake. The acquisition worker is a health surface only. The asset service
  performs bounded, traversal-resistant, content-digest-verified local reads.
- The React application implements loading, ready, degraded, and offline
  foundation states, keyboard skip navigation, reduced-motion styling, runtime
  response validation, and explicit "not yet in production"/analysis-refusal
  copy. It is not yet the MapLibre evidence viewer.
- The four domain directories document ownership only. There are no executable
  retrieval, simulation, segmentation, or flux modules. The dependency set has
  no xarray, Rasterio/GDAL, PyTorch, Dask, or MapLibre implementation yet.

### Current verification truth

| Command or gate | Current result | Evidence / failure |
|---|---|---|
| `make dev:preflight` | **Fail** | The isolated `.dev/cache/docker-config` hides the host Compose CLI plugin; the bounded Compose probe exits `125`. Docker Engine `29.7.2` and Compose `5.3.1` work outside that isolated config. No port in `4170`–`4179` is currently listening; the two repository Compose containers are stopped. |
| `make check` | **Fail** | Formatting and the package-boundary check pass. Ruff rejects `scripts/check_boundaries.py:153` and `scripts/devctl.py:1566` for complexity above 10. |
| `make typecheck` | **Fail** | Strict mypy reports four unreachable-code errors in `scripts/devctl.py:317,324,328,335`. |
| `make test` | **Fail** | Pytest: **338 passed, 1 failed**, 89.68% aggregate coverage. The failing macOS case expects `/usr/bin/make` to observe `DYLD_INSERT_LIBRARIES`, which macOS process protection strips before the child runs. Because pytest fails first, this Make target does not reach the web tests. |
| `pnpm run test` | Pass | Five runtime-contract tests pass with 100% lines/branches/functions on `contracts.ts`. |
| `make dependency-audit` | **Fail** | `evidence/dependency-audit.json` is stale relative to committed CI, Makefile, support-matrix, dependency-register, and script hashes. |
| `make eval` | Pass, Tier 0 only | Confirms honestly that no domain metric artifact is published; it is not methane evaluation evidence. |
| `pnpm run build` | Pass | TypeScript and Vite build the current foundation UI. This does not exercise containers or the product workflow. |
| GitHub CI | **Fail** | The workflow rejects the `LD_LIBRARY_PATH` injected by `actions/setup-python` during its first state-reset step, so `make verify-all` never runs in CI. |
| `make verify-all` from a clean checkout | **Not green / not established** | Blocked first by the red checks above; no current release/SBOM, integration, E2E, or clean-checkout artifact proves Tier 0. |

### Release-gate and submission position

- **G1:** zero held-out published-event reproductions; no immutable event
  manifest or regenerating command.
- **G2:** no fixed clean-scene benchmark, learned model, deletion ablation, or
  measured false-positive rate.
- **G3:** no scene masking, MBMP/MBSP retrieval, or empirical-null
  implementation, so fail-closed scene/null behavior is unproven.
- **G4:** no LUT, IME calculation, ERA5 adapter, wind sensitivity sweep, flux
  interval, or dominant-uncertainty output.
- **G5:** only foundation services are containerized; there is no reproducible
  scene-to-result pipeline replay.
- **G6:** the web foundation has accessibility checks, but no source-scene map,
  reference dates, plume overlay, uncertainty result, provenance chain, or
  result-adjacent coverage limits.
- The Devpost draft exists, but no product name is assigned and no truthful
  deployment, screenshots, demo video, evaluation claims, or final-submission
  evidence exists. The fixed deadline remains **2026-08-15 14:00 PT**.

### Next work, in `GOAL.md` §10.1 order

1. Restore Tier 0 truth: make repository-scoped Compose discovery work without
   trusting mutable user Docker configuration; fix the CI dynamic-loader
   environment boundary; resolve both Ruff findings, all four mypy findings,
   and the platform-invalid DYLD regression test without weakening the control.
2. Regenerate and review dependency evidence, then run `make check`, `make
   test`, `make test-integration`, `make test-e2e`, `make build`, `make eval`,
   `make sbom`, and finally `make verify-all` from a clean checkout. Archive the
   exact successful output and require a green GitHub CI run before claiming
   Tier 0 exit.
3. Reconcile documentation drift after the gate is factual: the idea dossier
   still says implementation has not started, the README says the Tier 0
   toolchain is locked despite red gates, deadline countdown prose is static,
   and ADR-0001 records an older observed Docker Engine version. Preserve the
   fixed deadline and design intent while separating snapshots from invariants.
4. Begin Tier 1 with typed/versioned domain contracts and property tests for all
   seven invariants. Do not start the attractive UI or publish an analysis
   endpoint while those contracts remain prose.
5. Run the Tier 2 kill test next: acquire a provenance-checked Sentinel-2 L1C
   target plus geometry/orbit-compatible references for one documented large
   event and determine whether MBMP/MBSP produces a visible signal against an
   empirical clean-scene null. Record failure as evidence rather than tuning on
   the held-out event.

- **Migration and rollback:** Documentation-only change; no schema, runtime,
  dependency, service, or generated-evidence mutation. Revert this entry to
  roll back the handoff.
- **Blocked items:** None external. Every current red item is repository work,
  not a credential, provider, or human-approval blocker.
