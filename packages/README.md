# Domain package ownership

These four directories are the permanent framework-independent methane-analysis
boundaries named by the repository architecture. At Tier 0 they intentionally
own contracts and acceptance criteria only: no analysis capability or production
claim exists yet. Executable modules enter a boundary only with invariant tests,
versioned provenance, and the dependency review for the vertical slice that uses
them.

Dependencies flow from applications/workers into these packages, never from a
domain package into `services/`, `workers/`, `apps/`, transport frameworks,
provider SDKs, or mutable process state. Cross-package imports require an ADR
when they create a new ownership edge.
