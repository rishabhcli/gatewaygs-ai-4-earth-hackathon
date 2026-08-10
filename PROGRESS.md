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
