# Foundation threat model

**Scope:** Tier 0 local service lifecycle, loopback HTTP surfaces, Docker
Compose infrastructure, and generated development artifacts. This document is
updated before any public endpoint, credential, provider adapter, or file parser
is added.

## Assets and trust boundaries

- Repository source, lockfiles, immutable evidence, and local development state.
- The host process table and the exclusive TCP block `4170–4179`, shared with no
  other repository by contract.
- Docker images and containers crossing the registry/daemon boundary.
- HTTP requests crossing into loopback-bound development services.
- `.dev/` files crossing from checked-in lifecycle code into mutable local state.

## Threats and structural controls

| Threat | Control | Failure behavior | Verification |
|---|---|---|---|
| A lifecycle command kills a process or container it did not start | Direct PID records include kernel start identity and a complete service/configuration digest. Delegated records are bound after startup to the full 64-hex Compose container ID; Compose project, canonical config/env/root labels, service/name, exact loopback publishers, and current config hash are reverified before use. Broad process/container sweeps are absent | Refuse every signal/stop when the record is missing, the PID identity changed, provenance drifted, or an otherwise identical container was recreated under a different ID | PID-reuse, missing/dead-wrapper, recreated-container, provenance, publisher, config-hash, and source-policy regression tests |
| A service binds a default or public interface | Host and port are typed/allowlisted; Compose mappings include `127.0.0.1`; strict-port startup is required | Refuse startup | Configuration and Compose policy tests |
| A TCP listener is mistaken for readiness | Health checks validate HTTP status and a typed service-specific payload; database/object storage use native or provider health probes | `dev:health` exits non-zero | Semantic-health unit and integration tests |
| Stale PID metadata targets a reused PID | Bind each record to the kernel-reported process start identity and require an exact match again before every signal; require the recorded service/config digest before treating a live service as reusable | Refuse to signal on an identity mismatch and preserve the record for diagnosis | PID-reuse, record-integrity, and signal-refusal regression tests |
| Malicious `.dev/` path escapes the repository | Resolve every managed path under the repository root; never execute commands loaded from mutable `.dev/` data | Refuse the path | Path-containment tests |
| Shared process or Docker metadata exhausts lifecycle memory | Capture lsof and Compose output through private temporary files, enforce byte limits before reading into memory, require UTF-8 and typed bounded parsers, and time out every child | Refuse oversized, malformed, non-UTF-8, or timed-out metadata without signalling a holder | Bounded-capture and parser-adversary tests |
| Dependency or image drift changes behavior | Lock language dependencies and pin container references; record direct-dependency review and generate an SBOM | Build or policy verification fails | Lock consistency and SBOM commands |
| Development endpoint is reached from another host | Bind every listener to `127.0.0.1`; do not rely on firewall policy | Listener is unreachable off-host | Socket/Compose binding inspection |
| Secret reaches logs or client assets | No provider credentials are used at Tier 0; synthetic local service credentials are generated under real, non-symlinked `.dev/secrets/` directories with mode `0600`, read through contained file references, and excluded from structured log fields | Refuse missing, short, permissive, non-regular, symlinked, or escaping secret paths; never echo values | Secret-boundary and log-redaction tests plus bundle scans before provider credentials are introduced |

Tier 0 does not claim that devctl authenticates a direct live process's full
command line or environment. Its direct-process boundary is the PID plus kernel
start identity, the repository-contained mode-`0700` state directory, and the
exact recorded configuration/environment digest. Delegated Docker ownership
adds canonical Compose provenance, a current config hash, exact publishers, an
independently version-probed Compose executable, and the persisted full
container ID. A missing or dead-wrapper record without the same container ID is
not recoverable automatically: devctl refuses rather than treating same-project
state as proof it created the container. A future multi-user host posture must
replace this local filesystem trust assumption with an OS-level supervisor or a
daemon-enforced unforgeable ownership token.

## Deferred production threats

Authentication, tenant authorization, Copernicus credentials and rate limits,
untrusted raster parsing, decompression bombs, SSRF through asset/provider URLs,
job replay, object-store policy, PostGIS row isolation, model artifact integrity,
and public denial of service are mandatory analyses before their boundaries are
implemented. They are not silently treated as solved by loopback isolation.
