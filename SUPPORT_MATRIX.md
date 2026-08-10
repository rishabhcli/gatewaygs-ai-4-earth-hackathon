# Support matrix

This matrix is deliberately conservative. `Unverified` means the system must
not present the capability as supported. Evidence links become valid only after
their committed regenerating commands pass from a clean checkout.

| Surface | Status | Declared support | Refusal outside support | Evidence |
|---|---|---|---|---|
| Local development host | Unverified | Apple silicon macOS with CPython 3.14.7, Node.js 24.19.0, uv 0.12.3, pnpm 11.21.0, Syft 1.49.0, Docker Engine >=24, Docker Compose >=2.24, GNU Make >=3.81, Git with `check-ignore`, and lsof with bounded TCP/listener field output | Toolchain/capability checks and port preflight fail closed with a stable diagnostic | Pending Tier 0 `verify-all` evidence |
| CI verification host | Unverified | GitHub-hosted Ubuntu 24.04 with the repository-pinned Python, Node, pnpm, uv, Syft and browser surfaces plus Docker Engine >=24 and Compose >=2.24 | CI toolchain and capability probes fail before build, tests, lifecycle, or evidence publication | Pending committed CI run URL/log |
| Sentinel-2 product level | Unverified | L1C only where top-of-atmosphere retrieval is required | L2A is rejected before retrieval | Pending Tier 1 property evidence |
| Analysis geography and surface | Unverified | None yet | No methane or flux result is emitted | Pending held-out evaluation evidence |
| Flux estimates | Unverified | None yet | Candidate may exist without flux; missing/stale wind abstains | Pending Tier 5 refusal evidence |
| Production deployment | Unsupported | None | UI and status surfaces state `not yet in production` | Pending every `GOAL.md` §5 condition |
