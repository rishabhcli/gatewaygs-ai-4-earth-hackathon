# Tier 0 executable contract. Keep syntax compatible with macOS GNU Make 3.81.

SHELL := /bin/sh

override PROJECT_NAME := gatewaygs-ai-4-earth-hackathon
PYTHON_VERSION := 3.14.7
NODE_VERSION := 24.19.0
UV_VERSION := 0.12.3
PNPM_VERSION := 11.21.0
SYFT_VERSION := 1.49.0

# dev-services.json intentionally launches uv, pnpm, and docker by canonical
# PATH names. Do not permit Make-only binary overrides that the lifecycle would
# silently bypass; exact/capability validation below applies to these same paths.
override UV_BIN := $(shell command -v uv 2>/dev/null)
override NODE_BIN := $(shell \
	for candidate in /opt/homebrew/opt/node@24/bin/node \
		/usr/local/opt/node@24/bin/node \
		"$$(command -v node 2>/dev/null)"; do \
		if test -n "$$candidate" && test -x "$$candidate" && \
			test "$$($$candidate --version 2>/dev/null)" = "v$(NODE_VERSION)"; then \
			echo "$$candidate"; exit 0; \
		fi; \
	done)
override NODE_BIN_DIR := $(patsubst %/,%,$(dir $(NODE_BIN)))
override PNPM_BIN := $(shell \
	for candidate in "$$(command -v pnpm 2>/dev/null)"; do \
		if test -n "$$candidate" && test -x "$$candidate" && \
			test "$$(PATH="$(NODE_BIN_DIR):$$PATH" $$candidate --version 2>/dev/null)" = "$(PNPM_VERSION)"; then \
			echo "$$candidate"; exit 0; \
		fi; \
	done)
override DOCKER_BIN := $(shell command -v docker 2>/dev/null)
override SYFT_BIN := $(shell command -v syft 2>/dev/null)

override DEV_ROOT := $(CURDIR)/.dev
override CACHE_ROOT := $(DEV_ROOT)/cache
override UV_CACHE := $(CACHE_ROOT)/uv
override UV_PYTHON_INSTALL_DIR := $(CACHE_ROOT)/python
override PNPM_STORE := $(CACHE_ROOT)/pnpm-store
override TOOL_HOME := $(CACHE_ROOT)/home
override XDG_CONFIG_ROOT := $(CACHE_ROOT)/xdg-config
override XDG_DATA_ROOT := $(CACHE_ROOT)/xdg-data
override XDG_STATE_ROOT := $(CACHE_ROOT)/xdg-state
override DOCKER_CONFIG_ROOT := $(CACHE_ROOT)/docker-config
override DOCKER_SOCKET_ENDPOINT := unix:///var/run/docker.sock
override TIER0_CATALOG_VOLUME := $(PROJECT_NAME)_catalog_data
override TIER0_OBJECT_VOLUME := $(PROJECT_NAME)_object_data
override TIER0_SYNTHETIC_VOLUMES := $(TIER0_CATALOG_VOLUME) $(TIER0_OBJECT_VOLUME)
REQUESTED_PLAYWRIGHT_BROWSERS_PATH := $(strip $(PLAYWRIGHT_BROWSERS_PATH))
override CANONICAL_PLAYWRIGHT_BROWSERS_PATH := $(CACHE_ROOT)/playwright
ifneq ($(REQUESTED_PLAYWRIGHT_BROWSERS_PATH),)
ifneq ($(abspath $(REQUESTED_PLAYWRIGHT_BROWSERS_PATH)),$(abspath $(CANONICAL_PLAYWRIGHT_BROWSERS_PATH)))
$(error PLAYWRIGHT_BROWSERS_PATH must remain at $(CANONICAL_PLAYWRIGHT_BROWSERS_PATH))
endif
endif
override PLAYWRIGHT_BROWSERS_PATH := $(CANONICAL_PLAYWRIGHT_BROWSERS_PATH)
VENV_PYTHON := $(CURDIR)/.venv/bin/python
EVALUATION_RUNNER := $(CURDIR)/scripts/run_evaluation.py

TOOL_ENV = env PATH="$(NODE_BIN_DIR):$(PATH)" \
	HOME="$(TOOL_HOME)" \
	TMPDIR="$(DEV_ROOT)/tmp" \
	TEMP="$(DEV_ROOT)/tmp" \
	TMP="$(DEV_ROOT)/tmp" \
	UV_CACHE_DIR="$(UV_CACHE)" \
	UV_PYTHON_INSTALL_DIR="$(UV_PYTHON_INSTALL_DIR)" \
	XDG_CACHE_HOME="$(CACHE_ROOT)/xdg" \
	XDG_CONFIG_HOME="$(XDG_CONFIG_ROOT)" \
	XDG_DATA_HOME="$(XDG_DATA_ROOT)" \
	XDG_STATE_HOME="$(XDG_STATE_ROOT)" \
	npm_config_cache="$(CACHE_ROOT)/npm" \
	PLAYWRIGHT_BROWSERS_PATH="$(PLAYWRIGHT_BROWSERS_PATH)" \
	DOCKER_CONFIG="$(DOCKER_CONFIG_ROOT)" \
	DOCKER_HOST="$(DOCKER_SOCKET_ENDPOINT)" \
	COMPOSE_PROJECT_NAME="$(PROJECT_NAME)"
UV = $(TOOL_ENV) "$(UV_BIN)"
PYTHON = $(UV) run --frozen --python "$(PYTHON_VERSION)" python
PYTHON_OFFLINE = $(UV) run --frozen --offline --python "$(PYTHON_VERSION)" python
PNPM = $(TOOL_ENV) "$(PNPM_BIN)"
COMPOSE = $(TOOL_ENV) "$(DOCKER_BIN)" compose --project-name "$(PROJECT_NAME)" \
	--env-file "$(CURDIR)/ports.env" --file "$(CURDIR)/compose.yaml"

.NOTPARALLEL:
.PHONY: bootstrap _reject-control-environment _secure-dev-root \
	_require-host-tools toolchain-check \
	container-toolchain-check \
	dependency-audit check lint format \
	format-check typecheck test test-integration test-e2e eval build sbom run-local \
	release-check verify-all reset-tier0-state _force-dev-command \
	dev\:preflight dev\:up dev\:health dev\:down

# GNU Make 3.81 does not honor an escaped-colon target as a .PHONY prerequisite.
# The phony force prerequisite keeps the user-facing dev:* commands unshadowable.
_force-dev-command:

# Correctness and daemon selection must not be redirected by ambient process
# configuration. Canonical repo-scoped cache values used by CI are the only
# supported exceptions. Report names only so a hostile value cannot reach logs.
_reject-control-environment:
	@set -u; \
	env | LC_ALL=C sort | while IFS='=' read -r name value; do \
		case "$$name" in \
			UV_CACHE_DIR) \
				test "$$value" = "$(UV_CACHE)" || { \
					echo "ERROR: unsupported control environment variable: $$name" >&2; \
					exit 1; \
				} ;; \
			UV_PYTHON_INSTALL_DIR) \
				test "$$value" = "$(UV_PYTHON_INSTALL_DIR)" || { \
					echo "ERROR: unsupported control environment variable: $$name" >&2; \
					exit 1; \
				} ;; \
			PLAYWRIGHT_BROWSERS_PATH) \
				test "$$value" = "$(PLAYWRIGHT_BROWSERS_PATH)" || { \
					echo "ERROR: unsupported control environment variable: $$name" >&2; \
					exit 1; \
				} ;; \
			COMPOSE_PROJECT_NAME) \
				test "$$value" = "$(PROJECT_NAME)" || { \
					echo "ERROR: unsupported control environment variable: $$name" >&2; \
					exit 1; \
				} ;; \
			XDG_CACHE_HOME) \
				test "$$value" = "$(CACHE_ROOT)/xdg" || { \
					echo "ERROR: unsupported control environment variable: $$name" >&2; \
					exit 1; \
				} ;; \
			npm_config_cache) \
				test "$$value" = "$(CACHE_ROOT)/npm" || { \
					echo "ERROR: unsupported control environment variable: $$name" >&2; \
					exit 1; \
				} ;; \
			PYTHONPATH|PYTHONHOME|PYTHONSTARTUP|PYTHONWARNINGS| \
			PYTEST_ADDOPTS|COVERAGE_*|NODE_OPTIONS|NODE_PATH| \
			NPM_CONFIG_*|npm_config_*|PNPM_CONFIG_*|pnpm_config_*| \
			UV_*|PLAYWRIGHT_*|DOCKER_*|COMPOSE_*|BUILDKIT_*|SYFT_*| \
			MYPY_*|RUFF_*|VITE_*|XDG_CONFIG_HOME|XDG_DATA_HOME| \
			XDG_STATE_HOME|LD_*|DYLD_*|BASH_ENV|ENV|NODE_BINARY) \
				echo "ERROR: unsupported control environment variable: $$name" >&2; \
				exit 1 ;; \
		esac; \
	done

_secure-dev-root: _reject-control-environment
	@set -u; \
	for directory in \
		"$(DEV_ROOT)" \
		"$(DEV_ROOT)/tmp" \
		"$(CACHE_ROOT)" \
		"$(UV_CACHE)" \
		"$(UV_PYTHON_INSTALL_DIR)" \
		"$(PNPM_STORE)" \
		"$(TOOL_HOME)" \
		"$(XDG_CONFIG_ROOT)" \
		"$(XDG_DATA_ROOT)" \
		"$(XDG_STATE_ROOT)" \
		"$(DOCKER_CONFIG_ROOT)" \
		"$(PLAYWRIGHT_BROWSERS_PATH)" \
		"$(CACHE_ROOT)/xdg" \
		"$(CACHE_ROOT)/npm"; do \
		if test -L "$$directory"; then \
			echo "ERROR: repository development directory must not be a symlink: $$directory" >&2; \
			exit 1; \
		fi; \
		mkdir -p "$$directory" || { \
			echo "ERROR: cannot create repository development directory: $$directory" >&2; \
			exit 1; \
		}; \
		if test -L "$$directory" || ! test -d "$$directory"; then \
			echo "ERROR: repository development path is not a real directory: $$directory" >&2; \
			exit 1; \
		fi; \
		chmod 700 "$$directory" || { \
			echo "ERROR: cannot secure repository development directory: $$directory" >&2; \
			exit 1; \
		}; \
	done

_require-host-tools: _secure-dev-root
	@test -n "$(UV_BIN)" || { echo "ERROR: uv $(UV_VERSION) is required" >&2; exit 1; }
	@test -n "$(NODE_BIN)" || { echo "ERROR: Node $(NODE_VERSION) is required" >&2; exit 1; }
	@test -n "$(PNPM_BIN)" || { echo "ERROR: pnpm $(PNPM_VERSION) is required" >&2; exit 1; }
	@test "$$(PATH="$(NODE_BIN_DIR):$$PATH" command -v uv 2>/dev/null)" = "$(UV_BIN)" || \
		{ echo "ERROR: lifecycle uv provenance differs from the checked executable" >&2; exit 1; }
	@test "$$(PATH="$(NODE_BIN_DIR):$$PATH" command -v node 2>/dev/null)" = "$(NODE_BIN)" || \
		{ echo "ERROR: lifecycle Node provenance differs from the checked executable" >&2; exit 1; }
	@test "$$(PATH="$(NODE_BIN_DIR):$$PATH" command -v pnpm 2>/dev/null)" = "$(PNPM_BIN)" || \
		{ echo "ERROR: lifecycle pnpm provenance differs from the checked executable" >&2; exit 1; }
	@case "$$($(UV_BIN) --version 2>/dev/null)" in \
		"uv $(UV_VERSION)"|"uv $(UV_VERSION) "*) ;; \
		*) echo "ERROR: uv $(UV_VERSION) is required" >&2; exit 1 ;; \
	esac
	@test "$$($(NODE_BIN) --version 2>/dev/null)" = "v$(NODE_VERSION)" || \
		{ echo "ERROR: Node $(NODE_VERSION) is required" >&2; exit 1; }
	@test "$$(PATH="$(NODE_BIN_DIR):$$PATH" $(PNPM_BIN) --version 2>/dev/null)" = "$(PNPM_VERSION)" || \
		{ echo "ERROR: pnpm $(PNPM_VERSION) is required" >&2; exit 1; }

bootstrap: _require-host-tools
	@$(UV) python find "$(PYTHON_VERSION)" >/dev/null 2>&1 || \
		$(UV) python install "$(PYTHON_VERSION)"
	@$(UV) sync --frozen --python "$(PYTHON_VERSION)"
	@$(PNPM) install --frozen-lockfile --store-dir "$(PNPM_STORE)"
	@$(PNPM) --filter @gatewaygs-ai-4-earth/web exec playwright install chromium
	@$(MAKE) --no-print-directory toolchain-check

toolchain-check: _require-host-tools
	@$(PYTHON) scripts/check_toolchain.py \
		--python "$(VENV_PYTHON)" \
		--node "$(NODE_BIN)" \
		--uv "$(UV_BIN)" \
		--pnpm "$(PNPM_BIN)"

container-toolchain-check: _require-host-tools
	@test -n "$(DOCKER_BIN)" || { echo "ERROR: Docker Engine >=24.0.0 is required" >&2; exit 1; }
	@test "$$(PATH="$(NODE_BIN_DIR):$$PATH" command -v docker 2>/dev/null)" = "$(DOCKER_BIN)" || \
		{ echo "ERROR: lifecycle Docker provenance differs from the checked executable" >&2; exit 1; }
	@$(PYTHON) scripts/check_toolchain.py \
		--python "$(VENV_PYTHON)" \
		--node "$(NODE_BIN)" \
		--uv "$(UV_BIN)" \
		--pnpm "$(PNPM_BIN)" \
		--docker "$(DOCKER_BIN)" \
		--require-containers
	@$(COMPOSE) config --quiet

dependency-audit: bootstrap
	@$(PYTHON_OFFLINE) scripts/dependency_audit.py \
		--write-evidence \
		--output "$(DEV_ROOT)/tmp/dependency-audit.json" \
		> "$(DEV_ROOT)/tmp/dependency-audit.stdout.json"
	@cmp -s "$(DEV_ROOT)/tmp/dependency-audit.json" evidence/dependency-audit.json || { \
		echo "ERROR: committed dependency audit evidence is stale" >&2; \
		diff -u evidence/dependency-audit.json "$(DEV_ROOT)/tmp/dependency-audit.json" >&2; \
		exit 1; \
	}
	@echo "DEPENDENCY AUDIT OK: register, locks, images, tools, and evidence agree"

# This is an intentionally destructive clean-checkout boundary for Tier 0 only.
# These two named volumes contain synthetic local PostGIS/MinIO state, never
# production or provider data. The default invocation previews and refuses;
# CI must bind authorization explicitly with TIER0_SYNTHETIC_RESET=1.
reset-tier0-state: _secure-dev-root
	@test -n "$(DOCKER_BIN)" || { echo "ERROR: Docker is required to reset Tier 0 state" >&2; exit 1; }
	@test "$$(PATH="$(NODE_BIN_DIR):$$PATH" command -v docker 2>/dev/null)" = "$(DOCKER_BIN)" || \
		{ echo "ERROR: lifecycle Docker provenance differs from the checked executable" >&2; exit 1; }
	@set -eu; \
	echo "RESET PREVIEW: only synthetic Tier 0 volumes may be deleted:"; \
	existing=""; \
	for volume in $(TIER0_SYNTHETIC_VOLUMES); do \
		matches="$$( \
			$(TOOL_ENV) "$(DOCKER_BIN)" volume ls --quiet \
				--filter "name=^$$volume$$" \
		)" || { \
			echo "ERROR: cannot inspect exact Tier 0 volume $$volume" >&2; \
			exit 1; \
		}; \
		case "$$matches" in \
			"") echo "  absent: $$volume" ;; \
			"$$volume") \
				echo "  present: $$volume"; \
				existing="$$existing $$volume" ;; \
			*) \
				echo "ERROR: Docker volume filter returned an inexact name for $$volume" >&2; \
				exit 1 ;; \
		esac; \
	done; \
	containers="$$( $(COMPOSE) ps --all --quiet )" || { \
		echo "ERROR: cannot preview repository Compose containers" >&2; \
		exit 1; \
	}; \
	if test -n "$$containers"; then \
		echo "REFUSED: repository Compose containers are owned by a running checkout" >&2; \
		echo "Run make dev:down in the owning checkout before resetting synthetic state" >&2; \
		exit 1; \
	else \
		echo "RESET PREVIEW: no repository Compose containers are present"; \
	fi; \
	if test "$(TIER0_SYNTHETIC_RESET)" != "1"; then \
		echo "REFUSED: synthetic Tier 0 data loss requires TIER0_SYNTHETIC_RESET=1" >&2; \
		exit 2; \
	fi; \
	for volume in $$existing; do \
		$(TOOL_ENV) "$(DOCKER_BIN)" volume rm "$$volume" >/dev/null || { \
			echo "ERROR: failed to remove exact Tier 0 volume $$volume" >&2; \
			exit 1; \
		}; \
	done; \
	echo "RESET OK: only named synthetic Tier 0 volumes were removed"

format: bootstrap
	@$(PYTHON) -m ruff check --fix --select I .
	@$(PYTHON) -m ruff format .
	@$(PNPM) run format

format-check: bootstrap
	@$(PYTHON) -m ruff format --check .
	@$(PNPM) run format:check

lint: bootstrap
	@$(PYTHON) scripts/check_boundaries.py
	@$(PYTHON) -m ruff check .
	@$(PNPM) run lint

typecheck: bootstrap
	@$(PYTHON) -m mypy
	@$(PNPM) run typecheck

check: format-check lint typecheck dependency-audit

test: bootstrap
	@$(PYTHON) -m pytest
	@$(PNPM) run test

test-integration: bootstrap
	@$(PYTHON) -m pytest --no-cov tests/test_devctl.py
	@set -u; integration_status=0; \
		$(MAKE) --no-print-directory dev:preflight && \
		$(MAKE) --no-print-directory dev:up && \
		$(MAKE) --no-print-directory dev:health || integration_status=$$?; \
		cleanup_status=0; \
		$(MAKE) --no-print-directory dev:down || cleanup_status=$$?; \
		if test $$integration_status -eq 0; then integration_status=$$cleanup_status; fi; \
		exit $$integration_status

test-e2e: bootstrap
	@set -u; status=0; \
		$(MAKE) --no-print-directory dev:preflight && \
		$(PNPM) run test:e2e && \
		$(MAKE) --no-print-directory dev:health || status=$$?; \
		cleanup_status=0; \
		$(MAKE) --no-print-directory dev:down || cleanup_status=$$?; \
		if test $$status -eq 0; then status=$$cleanup_status; fi; \
		exit $$status

eval: bootstrap
	@if test -f "$(EVALUATION_RUNNER)"; then \
		$(PYTHON) "$(EVALUATION_RUNNER)"; \
	else \
		$(PYTHON) scripts/check_boundaries.py --validate-tier0-evidence; \
	fi

build: bootstrap container-toolchain-check
	@$(PNPM) run build
	@$(COMPOSE) config --quiet
	@$(COMPOSE) pull catalog
	@$(COMPOSE) build minio

sbom: build
	@test -n "$(SYFT_BIN)" || { echo "ERROR: Syft $(SYFT_VERSION) is required" >&2; exit 1; }
	@$(PYTHON) scripts/generate_release_manifest.py \
		--syft "$(SYFT_BIN)" \
		--docker "$(DOCKER_BIN)" \
		--output-dir "$(DEV_ROOT)/release" \
		--verify-reproducible

dev\:preflight: _force-dev-command
	@$(MAKE) --no-print-directory container-toolchain-check
	@$(PYTHON) scripts/devctl.py preflight

dev\:up: bootstrap _force-dev-command
	@set -u; \
		$(MAKE) --no-print-directory container-toolchain-check && \
		$(PYTHON) scripts/dev_secrets.py ensure && \
		$(PYTHON) scripts/devctl.py preflight && \
		$(PYTHON) scripts/devctl.py up || exit $$?; \
	status=0; \
	$(PYTHON) scripts/init_object_store.py || status=$$?; \
	if test $$status -ne 0; then \
		cleanup_status=0; \
		$(PYTHON) scripts/devctl.py down || cleanup_status=$$?; \
		echo "ERROR: object-store initialization status=$$status; dev cleanup status=$$cleanup_status" >&2; \
		exit $$status; \
	fi

dev\:health: _force-dev-command _secure-dev-root
	@$(PYTHON) scripts/devctl.py health

dev\:down: _force-dev-command _secure-dev-root
	@$(PYTHON) scripts/devctl.py down

run-local: bootstrap
	@$(MAKE) --no-print-directory dev:up
	@$(MAKE) --no-print-directory dev:health

release-check: check test test-integration build test-e2e eval sbom

verify-all: release-check
