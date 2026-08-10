# Runtime configuration contract

Tier 0 application processes do **not** inherit the ambient host environment.
The lifecycle controller constructs a child allowlist containing host `PATH`,
locale/timezone, non-secret user labels, and only the two bounded tuning
variables below. It strips Python, Node, package-manager, Compose, Docker, and
dynamic-loader control variables. `HOME`, temporary files, XDG state, caches,
Docker configuration, and the Playwright profile are forced under the private
repository `.dev/` tree. Every network address, service role, port, repository
path, database identity, object-store endpoint, bucket, and asset directory is
code-owned for the loopback development boundary. A `GATEWAYGS_*` variable
outside this table causes startup to fail rather than redirecting a service.

| Variable | Type and bound | Default | Effect |
|---|---|---:|---|
| `GATEWAYGS_DEPENDENCY_TIMEOUT_SECONDS` | float, `0 < value <= 10` | `1.5` | Per-dependency readiness timeout for API and worker probes |
| `GATEWAYGS_MAX_ASSET_BYTES` | integer, `0 < value <= 1073741824` | `268435456` | Maximum verified content-addressed asset response size |

Lifecycle tuning is separate and consumed only by `scripts/devctl.py`. The
supported variables are `DEVCTL_STARTUP_GRACE_SECONDS` (`0`–`5`),
`DEVCTL_SHUTDOWN_TIMEOUT_SECONDS` (`0.1`–`60`),
`DEVCTL_HEALTH_TIMEOUT_SECONDS` (`0.05`–`600`), and
`DEVCTL_HEALTH_INTERVAL_SECONDS` (`0.01`–`5`). They change bounded waits only;
they cannot change commands, ports, hosts, paths, or ownership. Production mode
will require a separate ADR and secret-store-backed schema rather than widening
this local contract silently.

## Synthetic Tier 0 state reset

PostGIS and object storage use the exact Docker volumes
`gatewaygs-ai-4-earth-hackathon_catalog_data` and
`gatewaygs-ai-4-earth-hackathon_object_data`. They contain synthetic local
foundation state only; they are not a backup or a supported home for real
scenes. A second checkout intentionally sees the same namespace. Its newly
generated ignored Postgres password cannot authenticate to a volume initialized
by an earlier checkout.

Recover only after the checkout that owns any live service has run
`make dev:down`. Then run:

```sh
TIER0_SYNTHETIC_RESET=1 make reset-tier0-state
```

The command previews both exact volume names, refuses while any container in the
exact Compose project exists, and never runs Compose teardown or a broad Docker
prune. The acknowledgement is non-overridable except for the literal value `1`.
Successful reset irreversibly deletes both synthetic stores; the next
`make dev:up` creates fresh volumes and credentials. Do not use this procedure
for production, user, benchmark, or irreplaceable data.

Lifecycle and release commands use only the local Unix Docker endpoint
`unix:///var/run/docker.sock`. `DOCKER_HOST`, `DOCKER_CONTEXT`, dynamic-loader
variables, shell startup hooks, package-manager controls, and alternate cache or
Compose paths are rejected before repository state is mutated. A host whose
Docker engine is available only through another endpoint is outside the current
support matrix rather than silently redirected.
