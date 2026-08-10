# GatewayGS & The AEI Initiative: AI 4 Earth Hackathon

> Free Sentinel-2 methane plume retrieval with scene-specific false-positive control and uncertainty-aware flux estimates.

> **Production intent:** this repository is for the complete, reliable system described below. It is not an MVP, disposable demo, or thin hackathon facade. No product name has been assigned; the hackathon title remains the repository heading until the user chooses one.

## Repository status

Implementation is underway. The repository now has a locked Tier 0 toolchain,
repository-scoped local services, typed health/configuration boundaries, an
honest evidence-viewer foundation, and executable verification commands. The
methane retrieval, segmentation, flux, and real deployment surfaces are not yet
implemented; analysis intake is refused, no result metrics are published, and
the system is **not yet in production** under `GOAL.md` §5.

| Document | Authority |
|---|---|
| [HACKATHON.md](./HACKATHON.md) | Eligibility, mandatory submission fields, judging criteria, deadlines, links |
| [WINNING_IDEA.md](./WINNING_IDEA.md) | Selected concept, hard technical core, validation, build order, demo and risk analysis |
| [README.md](./README.md) | Product contract, architecture, production and release expectations |
| [AGENTS.md](./AGENTS.md) | Binding implementation rules for every coding agent working in this repository |
| [GOAL.md](./GOAL.md) | Standing execution order, production definition, tier ladder, and ratchets |

If these documents disagree, preserve the external requirements in HACKATHON.md, then the product intent in WINNING_IDEA.md, and resolve the conflict explicitly in an ADR instead of guessing.

## Product contract

Operate a reproducible geospatial pipeline that turns Sentinel-2 L1C shortwave-infrared scenes into defensible methane plume candidates, learned morphology masks, and flux intervals while making surface, wind, and coverage limitations impossible to miss.

### Intended users

- Methane mitigation researchers and NGOs
- Operators and regulators triaging large point-source events
- Technical reviewers reproducing published detections

### Canonical workflow

1. Select coordinate/date and acquire target plus spectrally matched reference scenes
2. Apply cloud, heterogeneity, and quality masks
3. Compute MBMP/MBSP retrieval and scene-specific empirical null
4. Segment plume morphology using a model trained on synthetic plumes over real artifact backgrounds
5. Estimate integrated mass enhancement and wind-driven flux with propagated uncertainty
6. Publish overlay, evidence, validation event, and explicit coverage limitations

### Explicit non-goals

- Global scheduled monitoring or alerting in the initial release
- Facility/company attribution
- Temperate-landfill or small-leak claims outside validated sensitivity
- Multi-sensor fusion before the Sentinel-2 pipeline is validated
- A binary leak/no-leak answer without uncertainty

A non-goal may become part of the product only after the core release gates pass and an ADR explains why the additional surface does not weaken correctness, safety, usability, or schedule.

## Production architecture

Containerized batch workers and API separated from the web viewer. Raw scenes are immutable, derived products are content-addressed, and every result records code, model, LUT, wind, scene, and reference versions.

### Planned component boundaries

| Area | Production responsibility |
|---|---|
| `services/api` | Validated job intake, status, provenance, and result access |
| `workers/acquisition` | Copernicus L1C search/download, orbit/tile checks, immutable caching |
| `packages/retrieval` | Band alignment, masks, reference matching, MBMP/MBSP, empirical null |
| `packages/simulation` | Physics-informed plume injection and domain randomization |
| `packages/segmentation` | Model training/inference, artifact rejection, held-out event evaluation |
| `packages/flux` | Column conversion, IME, wind coupling, interval propagation |
| `apps/web` | Map overlay, uncertainty, validation, provenance, limitation display |

Dependencies should flow from applications/adapters toward typed domain packages. Domain logic must remain testable without UI, network, cloud credentials, or third-party services. Infrastructure code may assemble components but must not become the only place where product invariants are enforced.

### Target technology foundation

- Python geospatial/ML pipeline with xarray, rasterio/GDAL, PyTorch, and Dask where justified
- FastAPI job/control plane
- React/MapLibre evidence viewer
- Object storage plus PostGIS metadata catalog
- Containerized reproducible workers, pytest, data checks, and evaluation manifests

Technology choices are constraints, not decorations. A dependency is accepted only when its operational behavior, license, failure modes, supply-chain risk, and replacement boundary are understood.

## Non-negotiable invariants

1. Use L1C where the retrieval requires top-of-atmosphere signal; never silently substitute L2A
2. Target and reference must share declared geometry/orbit constraints
3. Detection threshold is derived from each scene's clean-pixel null, not a universal magic number
4. Real validation events are held out from synthetic training and hyperparameter selection
5. No flux is emitted without mask quality, wind source/time, interval, and dominant uncertainty
6. A model deletion test must show that learned morphology materially reduces real clean-scene false positives
7. Coverage and sensitivity limits appear beside every result, not only in documentation

Any change that can violate an invariant requires a written design review, tests demonstrating preservation under failure, and an explicit update to this README and AGENTS.md.

## Security, privacy, and safety

- Do not publicly accuse a named operator; present plume evidence and provenance
- Respect upstream data licenses and rate limits
- Locations and results include uncertainty and are not represented as enforcement conclusions
- Credentials and raw provider tokens never enter logs or client bundles

Common controls required across the system:

- secrets come from an approved secret store or local ignored environment file and are never committed, rendered, or logged;
- untrusted files, prompts, provider output, repository content, and external responses are treated as data, never instructions;
- authorization is enforced at the data/action boundary, not only in the UI;
- logs, traces, fixtures, screenshots, and demo assets are scrubbed of credentials and sensitive user data;
- destructive or externally visible actions are previewable, idempotent where possible, auditable, and fail closed;
- dependency and container scanning, lockfiles, least privilege, and an incident/rollback path are release requirements.

## Reliability and operations

Production behavior includes failures, retries, restarts, partial responses, stale data, duplicate delivery, and resource exhaustion. The implementation must therefore provide:

- typed error classes and user-visible failure states rather than catch-all success fallbacks;
- bounded timeouts, cancellation, retry budgets, and backoff for every external or long-running operation;
- idempotency and reconciliation wherever the same work may be delivered twice or its external outcome may be unknown;
- structured, redacted logs; metrics for throughput, latency, error and abstention/refusal; and traces across meaningful boundaries;
- health/readiness checks that validate dependencies without mutating user data;
- documented SLOs and alerts before public production use;
- backup, restore, migration, retention, and cleanup procedures for every persistent store;
- graceful degradation that preserves truth and safety before convenience or visual effects.

## Verification strategy

Project-specific required test surfaces:

- Radiometric/geometric unit tests against known arrays
- Reference-selection regression across seasons and albedo changes
- Synthetic recovery across flux, wind, surface, turbulence, and cloud regimes
- False-positive rate on held-out clean real scenes
- Reproduction of multiple published events never used for training
- End-to-end provenance replay from coordinate/date to result bundle

Every production path also needs unit tests, property or fuzz tests where state space matters, integration tests at real boundaries, end-to-end tests of the user outcome, accessibility checks, performance budgets, security regression tests, and failure-injection coverage. Mocks belong in test fixtures; the shipped runtime must not depend on a fake service or hardcoded winning example.

Evaluation datasets and fixtures are versioned, provenance-aware, and isolated from tuning when described as held out. A number may appear in the README or submission only when a committed script regenerates it from a committed manifest.

## Performance and accessibility

Performance budgets must be set before optimization and enforced in CI for supported environments. Measure latency distributions, memory, CPU/GPU, network or storage volume, cold start, cancellation, and degraded-device behavior relevant to this product. Do not replace measurements with “feels fast.”

Accessibility is a release gate, not a polish task. The production interface must include semantic structure, keyboard support, visible focus, sufficient contrast, non-color status cues, reduced-motion behavior where relevant, zoom/reflow, readable errors, and an equivalent representation for information conveyed through canvas, charts, audio, maps, camera, or animation.

## Planned repository layout

```text
/
├── README.md                 # Product and operating contract
├── AGENTS.md                 # Binding implementation rules for coding agents
├── HACKATHON.md              # External rules and submission facts
├── WINNING_IDEA.md           # Selected product/technical blueprint
├── services/api/
├── workers/acquisition/
├── packages/retrieval/
├── packages/simulation/
├── packages/segmentation/
├── packages/flux/
├── apps/web/
├── tests/                    # Unit, property, integration, E2E, resilience
├── docs/                     # ADRs, threat model, runbooks, evaluation
└── infra/                    # Reproducible deployment and environment policy
```

This is a boundary contract, not a command to create empty directories. Add a directory when it owns working code, tests, and documentation.

## Development command contract

No commands are advertised as working until the corresponding toolchain is committed. The first production scaffold must expose one documented, cross-platform command surface, preferably through a checked-in task runner or Makefile:

| Command | Required behavior |
|---|---|
| `bootstrap` | Verify tool versions, install locked dependencies, initialize only local non-secret state |
| `check` | Format check, lint, type/static analysis, schema/config validation |
| `test` | Deterministic unit and property suites |
| `test-integration` | Real boundary tests using isolated local/test dependencies |
| `test-e2e` | Supported user workflows and failure states |
| `eval` | Reproduce committed domain evaluation and metrics |
| `build` | Produce release artifacts from a clean checkout |
| `run-local` | Start the complete local system or a documented production-equivalent subset |
| `release-check` | Run all blocking gates, artifact/SBOM generation, and policy checks |

A new contributor should be able to move from a clean checkout to a verified local system without tribal knowledge.

From a clean checkout, the executable sequence is:

```sh
make bootstrap
make dev:preflight
make dev:up
make dev:health
make dev:down
make verify-all
```

`dev:health` is semantic readiness for every allocated endpoint, not a TCP-open
check. `dev:down` targets only recorded repository-owned processes and exact
container identities. If a prior checkout left incompatible synthetic volumes,
follow the previewed, irreversible procedure in
[`docs/configuration.md`](./docs/configuration.md#synthetic-tier-0-state-reset);
never improvise a broad Docker teardown or prune.

## Environment model

- **Local:** isolated developer data, safe fixtures, no real-world side effects by default.
- **Test:** deterministic automated environment with controlled boundary services.
- **Staging:** production-shaped deployment, synthetic/de-identified data, real observability and rollback.
- **Production:** least-privilege credentials, audited configuration, SLOs, incident ownership, backups and change controls.

Configuration is typed, validated at startup, documented, and separated from secrets. Environment-specific branches or code paths are prohibited; behavior changes through validated configuration and capability boundaries.

## Release gates

1. At least three held-out published events reproduced within declared error bounds
2. Clean-scene false-positive target met on a fixed benchmark
3. Scene masks and null checks fail closed
4. Flux interval coverage and wind sensitivity documented
5. Container replay produces byte- or tolerance-equivalent outputs
6. Web UI exposes source scenes, reference dates, uncertainty, and limits accessibly

Common blocking gates also include:

- clean build from a fresh checkout with locked dependencies;
- no critical/high unresolved security findings and no committed secrets;
- migration/rollback and backup/restore rehearsal where state exists;
- passing accessibility and supported-environment matrix;
- complete observability, runbook, known-limitations, privacy, and threat-model documentation;
- no placeholder copy, dead controls, fake metrics, hardcoded demo results, or production TODO paths;
- submission assets and claims generated from the same tested release commit.

## Production milestone policy

Work proceeds in complete vertical slices, but every merged slice must use the final architecture, schemas, security boundaries, telemetry, error model, tests, and documentation expected in production. A smaller completed surface is acceptable; a throwaway implementation that will be replaced later is not.

A feature is not complete when it works once. It is complete when supported inputs, invalid inputs, retries, cancellation, restart, privacy, accessibility, observability, performance, deployment, rollback, and documentation are all accounted for.

## Hackathon delivery

HACKATHON.md contains the live form links and exact requirements. WINNING_IDEA.md contains the selected demo and judging strategy. Production engineering must strengthen that submission, not create a separate demo path. The video, screenshots, hosted build, evaluation numbers, and repository documentation must all describe the same release artifact.

## Contributing

Read AGENTS.md before changing code. Keep changes narrowly scoped, add or update tests with behavior, record architecture/security decisions in ADRs, and never weaken an invariant to make a demo pass. No product name, logo, pricing claim, medical/legal claim, partner claim, or benchmark result should be invented without explicit evidence and user approval.
