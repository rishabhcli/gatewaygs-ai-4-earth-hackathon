# This suite intentionally uses unittest so it also runs without project extras.
# ruff: noqa: PT009, PT027, SIM117
from __future__ import annotations

import dataclasses
import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from scripts import devctl

PORTS_ENV = """\
# gatewaygs-ai-4-earth-hackathon — exclusive block 4170-4179
PORT_0=4170   # FastAPI job control plane
PORT_1=4171   # React + MapLibre evidence viewer
PORT_2=4172   # Worker health/status endpoint
PORT_3=4173   # Tile/asset server for scene overlays
PORT_5=4175   # PostGIS metadata catalog
PORT_6=4176   # MinIO object storage
PORT_7=4177   # MinIO console
"""


def _service(name: str, port_envs: list[str]) -> dict[str, object]:
    script = (
        f"import json; print(json.dumps({{'service': {name!r}, 'status': 'ready'}}))"
    )
    health: list[dict[str, object]] = [
        {
            "port_env": port_env,
            "kind": "command-json",
            "argv": [sys.executable, "-c", script],
            "expect": {"service": name, "status": "ready"},
        }
        for port_env in port_envs
    ]
    return {
        "name": name,
        "port_envs": port_envs,
        "command": [sys.executable, "-c", "import time; time.sleep(60)"],
        "health": health,
    }


def _full_config() -> dict[str, object]:
    # Six foreground processes truthfully cover all seven allocated endpoints.
    return {
        "version": 1,
        "services": [
            _service("api", ["PORT_0"]),
            _service("web", ["PORT_1"]),
            _service("worker", ["PORT_2"]),
            _service("assets", ["PORT_3"]),
            _service("postgis", ["PORT_5"]),
            _service("minio", ["PORT_6", "PORT_7"]),
        ],
    }


def _empty_listeners() -> dict[int, list[devctl.Listener]]:
    return {port: [] for port in devctl.PORT_BLOCK}


def _record(
    service: str = "api",
    *,
    pid: int = 4242,
    identity: str = "owned-process",
    ports: tuple[int, ...] = (4170,),
    ownership: str = "direct",
) -> devctl.ProcessRecord:
    return devctl.ProcessRecord(
        service=service,
        pid=pid,
        identity=identity,
        command_digest="0" * 64,
        ports=ports,
        listener_ownership=ownership,
        started_at="2026-08-09T00:00:00+00:00",
        delegated_container_id=("c" * 64 if ownership == "delegated" else None),
    )


def _compose_labels(root: Path, service: str) -> str:
    config_hash = "a" * 64 if service == "catalog" else "b" * 64
    labels = {
        "com.docker.compose.project": devctl.PROJECT_NAME,
        "com.docker.compose.service": service,
        "com.docker.compose.project.config_files": str(root / "compose.yaml"),
        "com.docker.compose.project.environment_file": str(root / "ports.env"),
        "com.docker.compose.project.working_dir": str(root),
        "com.docker.compose.oneoff": "False",
        "com.docker.compose.container-number": "1",
        "com.docker.compose.config-hash": config_hash,
    }
    return ",".join(f"{key}={value}" for key, value in labels.items())


class DevctlTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / devctl.PROJECT_NAME
        self.root.mkdir()
        (self.root / "ports.env").write_text(PORTS_ENV, encoding="utf-8")
        (self.root / ".gitignore").write_text(".dev/\n", encoding="utf-8")
        self.output: list[str] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def controller(self, **environment: str) -> devctl.DevController:
        defaults = {
            "DEVCTL_STARTUP_GRACE_SECONDS": "0.01",
            "DEVCTL_SHUTDOWN_TIMEOUT_SECONDS": "0.2",
            "DEVCTL_HEALTH_TIMEOUT_SECONDS": "0.06",
            "DEVCTL_HEALTH_INTERVAL_SECONDS": "0.01",
        }
        defaults.update(environment)
        return devctl.DevController(
            self.root,
            environ=defaults,
            emit=self.output.append,
            verify_repository=False,
        )

    def write_config(self, config: dict[str, object] | None = None) -> Path:
        path = self.root / "dev-services.json"
        path.write_text(json.dumps(config or _full_config()), encoding="utf-8")
        return path

    @staticmethod
    def terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

    def test_ports_env_is_exact_and_rejects_drift(self) -> None:
        self.assertEqual(
            devctl.parse_ports_env(self.root / "ports.env"), devctl.PORT_SPECS
        )
        (self.root / "ports.env").write_text(
            PORTS_ENV.replace("PORT_0=4170", "PORT_0=8000"), encoding="utf-8"
        )
        with self.assertRaisesRegex(devctl.DevctlError, "exclusive allocation"):
            devctl.parse_ports_env(self.root / "ports.env")

        target = self.root / "real-ports.env"
        target.write_text(PORTS_ENV, encoding="utf-8")
        (self.root / "ports.env").unlink()
        (self.root / "ports.env").symlink_to(target)
        with self.assertRaisesRegex(devctl.DevctlError, "missing required"):
            devctl.parse_ports_env(self.root / "ports.env")

    def test_ports_env_refuses_missing_invalid_duplicate_and_full_drift(self) -> None:
        with self.assertRaisesRegex(devctl.DevctlError, "missing required"):
            devctl.parse_ports_env(self.root / "absent.env")

        invalid_inputs = {
            "invalid": PORTS_ENV + "export PORT_8=4178\n",
            "duplicate": PORTS_ENV + "PORT_0=4170\n",
        }
        for expected, contents in invalid_inputs.items():
            with self.subTest(expected=expected):
                path = self.root / f"{expected}.env"
                path.write_text(contents, encoding="utf-8")
                with self.assertRaisesRegex(devctl.DevctlError, expected):
                    devctl.parse_ports_env(path)

        drift = self.root / "drift.env"
        drift.write_text(
            PORTS_ENV.replace("PORT_0=4170", "PORT_0=4174").replace(
                "PORT_1=4171", "PORT_8=4178"
            ),
            encoding="utf-8",
        )
        with self.assertRaises(devctl.DevctlError) as caught:
            devctl.parse_ports_env(drift)
        message = str(caught.exception)
        self.assertIn("missing=", message)
        self.assertIn("extra=", message)
        self.assertIn("changed=", message)

    def test_low_level_config_validators_fail_closed(self) -> None:
        invalid_objects: list[object] = [None, [], {1: "value"}]
        for object_value in invalid_objects:
            with (
                self.subTest(object=object_value),
                self.assertRaisesRegex(devctl.DevctlError, "JSON object"),
            ):
                devctl._require_object(object_value, "value")
        with self.assertRaisesRegex(devctl.DevctlError, "unknown keys"):
            devctl._reject_unknown_keys({"unexpected": True}, set(), "value")

        invalid_argv: list[object] = [None, [], [""], [1]]
        for argv_value in invalid_argv:
            with (
                self.subTest(argv=argv_value),
                self.assertRaisesRegex(devctl.DevctlError, "argv array"),
            ):
                devctl._require_argv(argv_value, "argv")
        with self.assertRaisesRegex(devctl.DevctlError, "NUL"):
            devctl._require_argv(["echo", "bad\x00value"], "argv")
        self.assertEqual(devctl._require_argv(["echo", "ok"], "argv"), ("echo", "ok"))

        invalid_paths: list[object] = [
            None,
            "ready",
            "//foreign.test/ready",
            "/ready#fragment",
        ]
        for path_value in invalid_paths:
            with self.subTest(path=path_value), self.assertRaises(devctl.DevctlError):
                devctl._require_http_path(path_value, "path")
        self.assertEqual(devctl._require_http_path("/ready?q=1", "path"), "/ready?q=1")

        with self.assertRaisesRegex(devctl.DevctlError, "service='api'"):
            devctl._semantic_expect(
                {"expect": {"service": "other", "status": "ready"}},
                "health",
                "api",
            )
        for timeout in (True, "1", 0.01, 11):
            with (
                self.subTest(timeout=timeout),
                self.assertRaisesRegex(devctl.DevctlError, "between 0.05 and 10"),
            ):
                devctl._probe_timeout({"timeout_seconds": timeout}, "health")
        self.assertEqual(devctl._probe_timeout({}, "health"), 2.0)
        for status in (None, True, 199, 300):
            with (
                self.subTest(http_status=status),
                self.assertRaisesRegex(devctl.DevctlError, "explicit 2xx"),
            ):
                devctl._http_status({"expect_status": status}, "health")
        self.assertEqual(devctl._http_status({"expect_status": 204}, "health"), 204)

    def test_health_contract_parsers_cover_all_semantic_kinds(self) -> None:
        command = devctl._parse_health(
            {
                "port_env": "PORT_0",
                "kind": "command-json",
                "argv": ["probe"],
                "expect": {"service": "api", "status": "ready"},
            },
            "api",
            {"PORT_0"},
            0,
        )
        self.assertEqual(command.argv, ("probe",))

        http_json = devctl._parse_health(
            {
                "port_env": "PORT_0",
                "kind": "http-json",
                "path": "/ready",
                "expect_status": 200,
                "expect": {"service": "api", "status": "ready"},
            },
            "api",
            {"PORT_0"},
            0,
        )
        self.assertEqual(http_json.path, "/ready")

        http_text = devctl._parse_health(
            {
                "port_env": "PORT_0",
                "kind": "http-text",
                "path": "/health",
                "expect_status": 200,
                "expect_text": "stable-ready-marker",
            },
            "api",
            {"PORT_0"},
            0,
        )
        self.assertEqual(http_text.expect_text, "stable-ready-marker")

        ready = devctl._parse_health(
            {
                "port_env": "PORT_0",
                "kind": "http-ready",
                "path": "/minio/health/ready",
                "expect_status": 204,
                "expect_headers": {"X-Ready": "yes"},
            },
            "api",
            {"PORT_0"},
            0,
        )
        self.assertEqual(ready.expect_headers, {"x-ready": "yes"})

        invalid_health = [
            ({"port_env": "PORT_1", "kind": "http-json"}, "one of the service"),
            ({"port_env": "PORT_0", "kind": "tcp"}, "supported semantic"),
            (
                {
                    "port_env": "PORT_0",
                    "kind": "http-text",
                    "path": "/ready",
                    "expect_status": 200,
                    "expect_text": "short",
                },
                "stable marker",
            ),
            (
                {
                    "port_env": "PORT_0",
                    "kind": "http-ready",
                    "path": "/version",
                    "expect_status": 200,
                },
                "readiness/health",
            ),
            (
                {
                    "port_env": "PORT_0",
                    "kind": "http-ready",
                    "path": "/health",
                    "expect_status": 200,
                    "expect_headers": {"x-ready": 1},
                },
                "values must be strings",
            ),
        ]
        for raw, expected in invalid_health:
            with (
                self.subTest(expected=expected),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                devctl._parse_health(raw, "api", {"PORT_0"}, 0)

    def test_service_and_top_level_config_rejections_are_strict(self) -> None:
        base_service = _service("api", ["PORT_0"])
        invalid_services: list[tuple[dict[str, object], str]] = []
        for name in ("API", "", "a" * 64):
            candidate = dict(base_service)
            candidate["name"] = name
            invalid_services.append((candidate, "name must match"))
        for port_envs, expected in (
            ([], "non-empty string array"),
            ([1], "non-empty string array"),
            (["PORT_0", "PORT_0"], "duplicate"),
            (["PORT_4"], "leaves the exclusive allocation"),
        ):
            candidate = dict(base_service)
            candidate["port_envs"] = port_envs
            invalid_services.append((candidate, expected))
        candidate = dict(base_service)
        candidate["listener_ownership"] = "foreign"
        invalid_services.append((candidate, "listener_ownership"))
        candidate = dict(base_service)
        candidate["health"] = []
        invalid_services.append((candidate, "non-empty array"))
        candidate = dict(base_service)
        candidate["env"] = {"HOST": "foreign-bind"}
        invalid_services.append((candidate, "protected variables"))
        candidate = dict(base_service)
        candidate["env"] = {"SAFE": 1}
        invalid_services.append((candidate, "values must all be strings"))
        candidate = dict(base_service)
        candidate["env"] = {"PYTHONPATH": "/foreign/injected"}
        invalid_services.append((candidate, "unsupported variables"))
        candidate = dict(base_service)
        candidate["unknown"] = True
        invalid_services.append((candidate, "unknown keys"))
        for raw, expected in invalid_services:
            with (
                self.subTest(expected=expected),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                devctl._parse_service(raw, "service", set(), set())

        names = {"api"}
        with self.assertRaisesRegex(devctl.DevctlError, "duplicate service"):
            devctl._parse_service(base_service, "service", names, set())
        with self.assertRaisesRegex(devctl.DevctlError, "already owned"):
            devctl._parse_service(base_service, "service", set(), {"PORT_0"})

        for contents, expected in (
            ("{", "cannot read"),
            ("[]", "JSON object"),
            ('{"version": 1, "services": [], "extra": true}', "unknown keys"),
            ('{"version": 2, "services": []}', "version must be exactly 1"),
            ('{"version": 1, "services": []}', "non-empty array"),
        ):
            with (
                self.subTest(config=contents),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                path = self.root / "invalid-config.json"
                path.write_text(contents, encoding="utf-8")
                devctl.load_config(path)
        with self.assertRaisesRegex(
            devctl.DevctlError, "missing service configuration"
        ):
            devctl.load_config(self.root / "missing.json")

    def test_config_supports_one_foreground_process_with_two_ports(self) -> None:
        config = devctl.load_config(self.write_config())
        minio = next(service for service in config.services if service.name == "minio")
        self.assertEqual(minio.port_envs, ("PORT_6", "PORT_7"))
        self.assertEqual(tuple(item.port_env for item in minio.health), minio.port_envs)

    def test_config_rejects_raw_tcp_health_and_incomplete_port_coverage(self) -> None:
        config = _full_config()
        services = config["services"]
        assert isinstance(services, list)
        services[0]["health"][0]["kind"] = "tcp"
        with self.assertRaisesRegex(devctl.DevctlError, "semantic readiness"):
            devctl.load_config(self.write_config(config))

        config = _full_config()
        services = config["services"]
        assert isinstance(services, list)
        services.pop()
        with self.assertRaisesRegex(devctl.DevctlError, "do not cover allocated ports"):
            devctl.load_config(self.write_config(config))

    def test_lsof_parser_preserves_holder_identity_and_address(self) -> None:
        parsed = devctl.parse_lsof_machine_output(
            "p12345\ncpython3\nn127.0.0.1:4179\n", 4179
        )
        self.assertEqual(
            parsed,
            [devctl.Listener(4179, 12345, "python3", "127.0.0.1:4179")],
        )

    def test_lsof_parsers_ignore_malformed_data_and_deduplicate(self) -> None:
        raw = "\n".join(
            [
                "pbad",
                "cignored",
                "n127.0.0.1:4170",
                "p12",
                "c",
                "n127.0.0.1:4170",
                "n127.0.0.1:4170",
                "nmalformed",
                "n127.0.0.1:9999",
            ]
        )
        self.assertEqual(
            devctl.parse_lsof_machine_output(raw, 4170),
            [
                devctl.Listener(4170, 12, "unknown", "127.0.0.1:4170"),
                devctl.Listener(4170, 12, "unknown", "malformed"),
                devctl.Listener(4170, 12, "unknown", "127.0.0.1:9999"),
            ],
        )
        block = devctl.parse_lsof_block_output(raw)
        self.assertEqual(
            block[4170],
            [devctl.Listener(4170, 12, "unknown", "127.0.0.1:4170")],
        )
        self.assertEqual(block[4171], [])

    def test_lsof_execution_failures_never_degrade_to_blind_port_actions(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        with (
            mock.patch("scripts.devctl.shutil.which", return_value=None),
            self.assertRaisesRegex(devctl.DevctlError, "lsof is required"),
        ):
            controller._run_lsof("selector", "block")
        for failure in (OSError("denied"), subprocess.TimeoutExpired(["lsof"], 1)):
            with (
                self.subTest(failure=failure),
                mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/lsof"),
                mock.patch("scripts.devctl.subprocess.run", side_effect=failure),
                self.assertRaisesRegex(devctl.DevctlError, "cannot inspect"),
            ):
                controller._run_lsof("selector", "block")
        for stderr, expected in (("bad selector", "bad selector"), ("", "exit 2")):
            completed = subprocess.CompletedProcess(
                ["lsof"], 2, stdout="", stderr=stderr
            )
            with (
                self.subTest(stderr=stderr),
                mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/lsof"),
                mock.patch("scripts.devctl.subprocess.run", return_value=completed),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                controller._run_lsof("selector", "block")
        completed = subprocess.CompletedProcess(["lsof"], 1, stdout="p1\n", stderr="")
        with (
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/lsof"),
            mock.patch("scripts.devctl.subprocess.run", return_value=completed),
        ):
            self.assertEqual(controller._run_lsof("selector", "block"), "p1\n")

        oversized = subprocess.CompletedProcess(
            ["lsof"],
            0,
            stdout="x" * (devctl.MAX_LSOF_OUTPUT_BYTES + 1),
            stderr="",
        )
        with (
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/lsof"),
            mock.patch("scripts.devctl.subprocess.run", return_value=oversized),
            self.assertRaisesRegex(devctl.DevctlError, "stdout exceeded"),
        ):
            controller._run_lsof("selector", "block")

    def test_compose_plugin_probe_is_isolated_versioned_and_bounded(self) -> None:
        controller = self.controller(HOME="/untrusted/ambient-home")
        controller._ensure_layout()
        compose = Path("/usr/local/lib/docker/cli-plugins/docker-compose")
        environment = controller._isolated_base_environment()
        good = subprocess.CompletedProcess(
            [str(compose)], 0, stdout="2.24.0\n", stderr=""
        )
        with (
            mock.patch(
                "scripts.devctl.resolve_compose_executable", return_value=compose
            ) as resolve,
            mock.patch("scripts.devctl.subprocess.run", return_value=good) as run,
        ):
            self.assertEqual(
                controller._verified_compose_executable("/usr/bin/docker", environment),
                compose,
            )
            self.assertEqual(
                controller._verified_compose_executable("/usr/bin/docker", environment),
                compose,
            )
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(resolve.call_args.args[1]["HOME"], str(controller.home_dir))
        self.assertNotEqual(
            resolve.call_args.args[1]["HOME"], "/untrusted/ambient-home"
        )

        for version, expected in (
            ("2.23.9\n", ">=2.24.0"),
            ("not-a-version\n", "malformed version"),
        ):
            candidate = self.controller()
            candidate._ensure_layout()
            completed = subprocess.CompletedProcess(
                [str(compose)], 0, stdout=version, stderr=""
            )
            with (
                self.subTest(version=version),
                mock.patch(
                    "scripts.devctl.resolve_compose_executable", return_value=compose
                ),
                mock.patch("scripts.devctl.subprocess.run", return_value=completed),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                candidate._verified_compose_executable(
                    "/usr/bin/docker", candidate._isolated_base_environment()
                )

    def test_scoped_compose_capture_refuses_oversized_output(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        (self.root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        oversized = subprocess.CompletedProcess(
            ["docker-compose"],
            0,
            stdout="x" * (devctl.MAX_COMPOSE_PS_BYTES + 1),
            stderr="",
        )
        with (
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/docker"),
            mock.patch.object(
                controller,
                "_verified_compose_executable",
                return_value=Path("/usr/bin/docker-compose"),
            ),
            mock.patch("scripts.devctl.subprocess.run", return_value=oversized),
            self.assertRaisesRegex(devctl.DevctlError, "stdout exceeded"),
        ):
            controller._run_scoped_compose(("ps",), "oversize test")

    def test_compose_inventory_parser_requires_exact_typed_records(self) -> None:
        publisher = {
            "URL": "127.0.0.1",
            "PublishedPort": 4175,
            "TargetPort": 5432,
            "Protocol": "tcp",
        }
        record = {
            "Project": devctl.PROJECT_NAME,
            "Service": "catalog",
            "State": "running",
            "Name": f"{devctl.PROJECT_NAME}-catalog-1",
            "ID": "c" * 64,
            "Labels": "label=value",
            "Publishers": [publisher],
        }
        expected = {
            "catalog": devctl.ComposeServiceRecord(
                container_id="c" * 64,
                state="running",
                name=f"{devctl.PROJECT_NAME}-catalog-1",
                publishers=frozenset({("127.0.0.1", 4175, 5432, "tcp")}),
                labels={"label": "value"},
            )
        }
        self.assertEqual(
            devctl.parse_compose_ps_publishers(json.dumps(record) + "\n"), expected
        )

        invalid: list[tuple[str, str]] = [
            ("not-json", "not JSON"),
            (json.dumps([]), "JSON object"),
            (json.dumps({**record, "Project": "foreign"}), "foreign project"),
            (json.dumps({**record, "Service": "BAD"}), "invalid service"),
            (json.dumps({**record, "ID": "short"}), "invalid service"),
            (json.dumps({**record, "Labels": None}), "invalid Docker labels"),
            (json.dumps({**record, "Labels": "malformed"}), "malformed Docker"),
            (
                json.dumps({**record, "Labels": "same=1,same=2"}),
                "duplicate/empty Docker labels",
            ),
            (
                json.dumps({**record, "Publishers": [{**publisher, "URL": 1}]}),
                "invalid published-port",
            ),
            (
                json.dumps({**record, "Publishers": [publisher, publisher]}),
                "duplicate published-port",
            ),
            (
                json.dumps(record) + "\n" + json.dumps(record),
                "duplicate records",
            ),
            ("x" * (devctl.MAX_COMPOSE_PS_BYTES + 1), "exceeded 256 KiB"),
        ]
        for raw, expected_error in invalid:
            with (
                self.subTest(expected=expected_error),
                self.assertRaisesRegex(devctl.DevctlError, expected_error),
            ):
                devctl.parse_compose_ps_publishers(raw)

        self.assertEqual(
            devctl.parse_compose_config_hashes(
                f"catalog {'a' * 64}\nminio {'b' * 64}\n"
            ),
            {"catalog": "a" * 64, "minio": "b" * 64},
        )
        for raw, expected_error in (
            ("catalog short", "invalid"),
            (f"catalog {'a' * 64}\ncatalog {'b' * 64}", "duplicate"),
            ("x" * (devctl.MAX_HEALTH_BODY_BYTES + 1), "exceeded 64 KiB"),
        ):
            with (
                self.subTest(hash_error=expected_error),
                self.assertRaisesRegex(devctl.DevctlError, expected_error),
            ):
                devctl.parse_compose_config_hashes(raw)

    def test_delegated_ownership_requires_exact_scoped_compose_publishers(
        self,
    ) -> None:
        controller = self.controller()
        controller._ensure_layout()
        (self.root / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        postgis = _record("postgis", pid=5001, ports=(4175,), ownership="delegated")
        minio = dataclasses.replace(
            _record("minio", pid=5002, ports=(4176, 4177), ownership="delegated"),
            delegated_container_id="d" * 64,
        )
        records = {"postgis": postgis, "minio": minio}
        config_hashes = {"catalog": "a" * 64, "minio": "b" * 64}
        output = "\n".join(
            json.dumps(value)
            for value in (
                {
                    "Project": devctl.PROJECT_NAME,
                    "Service": "catalog",
                    "State": "running",
                    "Name": f"{devctl.PROJECT_NAME}-catalog-1",
                    "ID": "c" * 64,
                    "Labels": _compose_labels(controller.root, "catalog"),
                    "Publishers": [
                        {
                            "URL": "127.0.0.1",
                            "PublishedPort": 4175,
                            "TargetPort": 5432,
                            "Protocol": "tcp",
                        }
                    ],
                },
                {
                    "Project": devctl.PROJECT_NAME,
                    "Service": "minio",
                    "State": "running",
                    "Name": f"{devctl.PROJECT_NAME}-minio-1",
                    "ID": "d" * 64,
                    "Labels": _compose_labels(controller.root, "minio"),
                    "Publishers": [
                        {
                            "URL": "127.0.0.1",
                            "PublishedPort": 4176,
                            "TargetPort": 9000,
                            "Protocol": "tcp",
                        },
                        {
                            "URL": "127.0.0.1",
                            "PublishedPort": 4177,
                            "TargetPort": 9001,
                            "Protocol": "tcp",
                        },
                    ],
                },
            )
        )
        completed = subprocess.CompletedProcess(["docker"], 0, stdout=output, stderr="")
        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            mock.patch.object(
                controller, "_compose_config_hashes", return_value=config_hashes
            ),
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/docker"),
            mock.patch.object(
                controller,
                "_verified_compose_executable",
                return_value=Path("/usr/bin/docker-compose"),
            ),
            mock.patch("scripts.devctl.subprocess.run", return_value=completed) as run,
        ):
            self.assertEqual(
                controller._delegated_compose_ports(records),
                {
                    ("postgis", 4175),
                    ("minio", 4176),
                    ("minio", 4177),
                },
            )
        argv = run.call_args.args[0]
        self.assertIn("--project-name", argv)
        self.assertIn("--all", argv)
        self.assertIn("--no-trunc", argv)
        self.assertEqual(run.call_args.kwargs["cwd"], self.root.resolve())

        wrong_target = output.replace('"TargetPort": 9001', '"TargetPort": 9002')
        bad = subprocess.CompletedProcess(["docker"], 0, stdout=wrong_target, stderr="")
        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            mock.patch.object(
                controller, "_compose_config_hashes", return_value=config_hashes
            ),
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/docker"),
            mock.patch.object(
                controller,
                "_verified_compose_executable",
                return_value=Path("/usr/bin/docker-compose"),
            ),
            mock.patch("scripts.devctl.subprocess.run", return_value=bad),
            self.assertRaisesRegex(devctl.DevctlError, "ownership mismatch"),
        ):
            controller._delegated_compose_ports(records)

        wrong_provenance = output.replace(
            str(controller.root / "compose.yaml"), "/foreign/compose.yaml"
        )
        bad = subprocess.CompletedProcess(
            ["docker"], 0, stdout=wrong_provenance, stderr=""
        )
        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            mock.patch.object(
                controller, "_compose_config_hashes", return_value=config_hashes
            ),
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/docker"),
            mock.patch.object(
                controller,
                "_verified_compose_executable",
                return_value=Path("/usr/bin/docker-compose"),
            ),
            mock.patch("scripts.devctl.subprocess.run", return_value=bad),
            self.assertRaisesRegex(devctl.DevctlError, "provenance mismatch"),
        ):
            controller._delegated_compose_ports(records)

        foreign = _record("foreign", pid=5003, ports=(4175,), ownership="delegated")
        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            self.assertRaisesRegex(devctl.DevctlError, "no scoped Compose mapping"),
        ):
            controller._delegated_compose_ports({"foreign": foreign})

    def test_process_identity_platform_backends_fail_closed(self) -> None:
        self.assertIsNone(devctl.process_identity(1))
        with (
            mock.patch("scripts.devctl.platform.system", return_value="Linux"),
            mock.patch(
                "scripts.devctl._procfs_identity", return_value="linux"
            ) as probe,
        ):
            self.assertEqual(devctl.process_identity(42), "linux")
            probe.assert_called_once_with(42)
        with (
            mock.patch("scripts.devctl.platform.system", return_value="Darwin"),
            mock.patch("scripts.devctl._darwin_identity", return_value="darwin"),
        ):
            self.assertEqual(devctl.process_identity(42), "darwin")
        with (
            mock.patch("scripts.devctl.platform.system", return_value="Other"),
            mock.patch("scripts.devctl._ps_identity", return_value="ps"),
        ):
            self.assertEqual(devctl.process_identity(42), "ps")

        valid_stat = "42 (worker name) " + " ".join(
            ["S", *("x" for _ in range(18)), "start-ticks"]
        )
        with mock.patch("scripts.devctl.Path.read_text", return_value=valid_stat):
            self.assertEqual(devctl._procfs_identity(42), "proc:42:start-ticks")
        for result in (
            "malformed",
            "42 (worker) " + " ".join(["Z", *("x" for _ in range(19))]),
        ):
            with mock.patch("scripts.devctl.Path.read_text", return_value=result):
                self.assertIsNone(devctl._procfs_identity(42))
        with mock.patch(
            "scripts.devctl.Path.read_text", side_effect=PermissionError("denied")
        ):
            self.assertIsNone(devctl._procfs_identity(42))

        with mock.patch("scripts.devctl.sys.platform", "linux"):
            self.assertIsNone(devctl._darwin_identity(42))
        with mock.patch("scripts.devctl.ctypes.CDLL", side_effect=OSError("missing")):
            self.assertIsNone(devctl._darwin_identity(42))

        ps_success = subprocess.CompletedProcess(
            ["ps"], 0, stdout="S Mon Aug  9 12:00:00 2026 python\n", stderr=""
        )
        with mock.patch("scripts.devctl.subprocess.run", return_value=ps_success):
            self.assertRegex(devctl._ps_identity(42) or "", r"^ps:[0-9a-f]{64}$")
        for ps_result in (
            subprocess.CompletedProcess(["ps"], 1, stdout="", stderr=""),
            subprocess.CompletedProcess(["ps"], 0, stdout="Z zombie", stderr=""),
        ):
            with mock.patch("scripts.devctl.subprocess.run", return_value=ps_result):
                self.assertIsNone(devctl._ps_identity(42))
        with mock.patch(
            "scripts.devctl.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["ps"], 1),
        ):
            self.assertIsNone(devctl._ps_identity(42))

    def test_layout_refuses_wrong_repository_missing_root_symlink_and_unignored_state(
        self,
    ) -> None:
        with self.assertRaisesRegex(devctl.DevctlError, "exact source checkout"):
            devctl.DevController(
                self.root.parent / "wrong-repository",
                environ={},
                emit=self.output.append,
                verify_repository=True,
            )
        same_name = self.root.parent / "other" / devctl.PROJECT_NAME
        same_name.mkdir(parents=True)
        with self.assertRaisesRegex(devctl.DevctlError, "exact source checkout"):
            devctl.DevController(same_name, verify_repository=True)

        missing = devctl.DevController(
            self.root / "missing", environ={}, verify_repository=False
        )
        with self.assertRaisesRegex(devctl.DevctlError, "does not exist"):
            missing._ensure_layout()

        outside = self.root / "outside"
        outside.mkdir()
        (self.root / ".dev").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(devctl.DevctlError, "not a real directory"):
            self.controller()._ensure_layout()
        (self.root / ".dev").unlink()

        (self.root / ".dev").mkdir(mode=0o755)
        (self.root / ".dev").chmod(0o755)
        self.controller()._ensure_layout()
        self.assertEqual(stat.S_IMODE((self.root / ".dev").stat().st_mode), 0o700)

        outside_lock = self.root / "outside-lock"
        outside_lock.write_text("unchanged", encoding="utf-8")
        (self.root / ".dev" / "devctl.lock").symlink_to(outside_lock)
        with self.assertRaisesRegex(devctl.DevctlError, "real repository lifecycle"):
            with self.controller()._lock():
                self.fail("symlinked lock must never be acquired")
        self.assertEqual(outside_lock.read_text(encoding="utf-8"), "unchanged")
        (self.root / ".dev" / "devctl.lock").unlink()

        checked = subprocess.CompletedProcess(["git"], 1, stdout=b"", stderr=b"")
        with (
            mock.patch("scripts.devctl.REPOSITORY_ROOT", self.root.resolve()),
            mock.patch("scripts.devctl.shutil.which", return_value=None),
            self.assertRaisesRegex(devctl.DevctlError, "git is required"),
        ):
            devctl.DevController(self.root, verify_repository=True)._ensure_layout()
        with (
            mock.patch("scripts.devctl.REPOSITORY_ROOT", self.root.resolve()),
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/git"),
            mock.patch("scripts.devctl.subprocess.run", return_value=checked),
            self.assertRaisesRegex(devctl.DevctlError, "not git-ignored"),
        ):
            devctl.DevController(self.root, verify_repository=True)._ensure_layout()

    def test_repository_mode_refuses_foreign_or_symlinked_command_config(self) -> None:
        foreign = self.root.parent / "foreign.json"
        foreign.write_text(json.dumps(_full_config()), encoding="utf-8")

        with self.assertRaisesRegex(devctl.DevctlError, "cannot be overridden"):
            with mock.patch("scripts.devctl.REPOSITORY_ROOT", self.root.resolve()):
                devctl.DevController(
                    self.root,
                    config_path=foreign,
                    verify_repository=True,
                )
        with self.assertRaisesRegex(devctl.DevctlError, "unsupported lifecycle"):
            with mock.patch("scripts.devctl.REPOSITORY_ROOT", self.root.resolve()):
                devctl.DevController(
                    self.root,
                    environ={"DEVCTL_CONFIG": str(foreign)},
                    verify_repository=True,
                )

        with (
            mock.patch("scripts.devctl.REPOSITORY_ROOT", self.root.resolve()),
            self.assertRaisesRegex(devctl.DevctlError, "unsupported lifecycle"),
        ):
            devctl.DevController(
                self.root,
                environ={"DEVCTL_UNDOCUMENTED": "1"},
                verify_repository=True,
            )

        injectable = devctl.DevController(
            self.root,
            config_path=foreign,
            verify_repository=False,
        )
        self.assertEqual(injectable.config_path, foreign)

        canonical = self.root / "dev-services.json"
        canonical.symlink_to(foreign)
        checked = subprocess.CompletedProcess(["git"], 0, stdout=b"", stderr=b"")
        with (
            mock.patch("scripts.devctl.REPOSITORY_ROOT", self.root.resolve()),
            mock.patch("scripts.devctl.shutil.which", return_value="/usr/bin/git"),
            mock.patch("scripts.devctl.subprocess.run", return_value=checked),
            self.assertRaisesRegex(devctl.DevctlError, "non-symlink"),
        ):
            devctl.DevController(self.root, verify_repository=True)._ensure_layout()

    def test_pid_record_decoder_and_loader_reject_tampering(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        source = controller._record_path("api")
        valid = _record().to_json()
        self.assertEqual(controller._decode_record(valid, source), _record())

        invalid_cases: list[tuple[str, object, str]] = [
            ("not-object", [], "JSON object"),
            (
                "missing",
                {key: value for key, value in valid.items() if key != "pid"},
                "invalid or foreign",
            ),
            ("foreign", {**valid, "project": "foreign"}, "invalid or foreign"),
            ("service", {**valid, "service": "API"}, "invalid service"),
            ("pid-bool", {**valid, "pid": True}, "invalid PID"),
            ("pid-low", {**valid, "pid": 1}, "invalid PID"),
            ("identity", {**valid, "identity": ""}, "invalid process identity"),
            ("digest", {**valid, "command_digest": "bad"}, "invalid command digest"),
            ("ports-empty", {**valid, "ports": []}, "invalid ports"),
            ("ports-bool", {**valid, "ports": [True]}, "invalid ports"),
            ("ports-range", {**valid, "ports": [4174]}, "invalid ports"),
            ("ports-duplicate", {**valid, "ports": [4170, 4170]}, "invalid ports"),
            (
                "ownership",
                {**valid, "listener_ownership": "foreign"},
                "invalid listener ownership",
            ),
            (
                "container-identity",
                {**valid, "delegated_container_id": "short"},
                "invalid delegated container identity",
            ),
            ("timestamp", {**valid, "started_at": ""}, "invalid start timestamp"),
            ("unknown", {**valid, "extra": True}, "unknown keys"),
        ]
        for name, payload, expected in invalid_cases:
            with (
                self.subTest(case=name),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                controller._decode_record(payload, source)
        mismatch = controller.pids_dir / "web.json"
        with self.assertRaisesRegex(devctl.DevctlError, "filename/service mismatch"):
            controller._decode_record(valid, mismatch)

        source.write_text("{", encoding="utf-8")
        source.chmod(0o600)
        with self.assertRaisesRegex(devctl.DevctlError, "cannot read PID record"):
            controller._load_records()
        source.unlink()
        target = self.root / "record-target"
        target.write_text(json.dumps(valid), encoding="utf-8")
        source.symlink_to(target)
        with self.assertRaisesRegex(devctl.DevctlError, "symlinked PID record"):
            controller._load_records()

    def test_pid_record_loader_refuses_fifo_oversize_and_permissions(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        source = controller._record_path("api")

        os.mkfifo(source, mode=0o600)
        with self.assertRaisesRegex(devctl.DevctlError, "regular file"):
            controller._load_records()
        source.unlink()

        source.write_bytes(b"{" + (b" " * devctl.MAX_PID_RECORD_BYTES) + b"}")
        source.chmod(0o600)
        with self.assertRaisesRegex(devctl.DevctlError, "exceeds size limit"):
            controller._load_records()
        source.unlink()

        source.write_text(json.dumps(_record().to_json()), encoding="utf-8")
        source.chmod(0o644)
        with self.assertRaisesRegex(devctl.DevctlError, "permissions must be 0600"):
            controller._load_records()

    def test_pid_record_writer_refuses_preexisting_temporary_paths(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        temporary = controller._record_path("api").with_suffix(".json.tmp")

        os.mkfifo(temporary, mode=0o600)
        with self.assertRaisesRegex(devctl.DevctlError, "cannot create private"):
            controller._write_record(_record())
        self.assertTrue(stat.S_ISFIFO(temporary.lstat().st_mode))
        temporary.unlink()

        temporary.write_text("foreign", encoding="utf-8")
        temporary.chmod(0o644)
        with self.assertRaisesRegex(devctl.DevctlError, "cannot create private"):
            controller._write_record(_record())
        self.assertEqual(stat.S_IMODE(temporary.stat().st_mode), 0o644)

    def test_preflight_reports_foreign_holder_without_killing_it(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.addCleanup(self.terminate, process)
        controller = self.controller()

        listeners = _empty_listeners()
        listeners[4179] = [
            devctl.Listener(4179, process.pid, "python-test", "127.0.0.1:4179")
        ]

        with mock.patch.object(controller, "_all_listeners", return_value=listeners):
            with self.assertRaisesRegex(devctl.DevctlError, "foreign holder"):
                controller.preflight()
        self.assertIsNone(
            process.poll(), "preflight must never signal a foreign process"
        )
        self.assertTrue(any(f"pid={process.pid}" in line for line in self.output))

    def test_preflight_rejects_non_loopback_binding_even_for_owned_pid(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.addCleanup(self.terminate, process)
        controller = self.controller()
        controller._ensure_layout()
        identity = devctl.process_identity(process.pid)
        self.assertIsNotNone(identity)
        record = devctl.ProcessRecord(
            service="api",
            pid=process.pid,
            identity=identity or "",
            command_digest="0" * 64,
            ports=(4170,),
            listener_ownership="direct",
            started_at="2026-08-09T00:00:00+00:00",
        )
        controller._write_record(record)

        listeners = _empty_listeners()
        listeners[4170] = [devctl.Listener(4170, process.pid, "python-test", "*:4170")]

        with mock.patch.object(controller, "_all_listeners", return_value=listeners):
            with self.assertRaisesRegex(devctl.DevctlError, "not 127.0.0.1"):
                controller.preflight()
        self.assertIsNone(process.poll())

    def test_up_fails_closed_when_product_config_is_missing(self) -> None:
        controller = self.controller()
        with (
            mock.patch.object(
                controller, "_all_listeners", return_value=_empty_listeners()
            ),
            self.assertRaisesRegex(devctl.DevctlError, "refusing to fabricate"),
        ):
            controller.up()
        self.assertEqual(list((self.root / ".dev" / "pids").glob("*.json")), [])

    def test_up_and_down_track_and_stop_only_owned_ephemeral_processes(self) -> None:
        self.write_config()
        foreign = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.addCleanup(self.terminate, foreign)
        controller = self.controller()
        with mock.patch.object(
            controller, "_all_listeners", return_value=_empty_listeners()
        ):
            controller.up()
            records = controller._load_records()
            self.assertEqual(
                set(records), {"api", "web", "worker", "assets", "postgis", "minio"}
            )
            self.assertTrue(
                all(controller._record_is_live(record) for record in records.values())
            )
            self.assertNotIn(foreign.pid, {record.pid for record in records.values()})
            controller.down()
        self.assertIsNone(
            foreign.poll(), "targeted shutdown must not touch unrelated processes"
        )
        self.assertEqual(list((self.root / ".dev" / "pids").glob("*.json")), [])
        for record in records.values():
            deadline = time.monotonic() + 1
            while (
                time.monotonic() < deadline
                and devctl.process_identity(record.pid) is not None
            ):
                time.sleep(0.01)
            self.assertIsNone(devctl.process_identity(record.pid))

    def test_down_refuses_pid_reuse_identity_mismatch(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.addCleanup(self.terminate, process)
        controller = self.controller()
        controller._ensure_layout()
        controller._write_record(
            devctl.ProcessRecord(
                service="api",
                pid=process.pid,
                identity="not-this-process",
                command_digest="0" * 64,
                ports=(4170,),
                listener_ownership="direct",
                started_at="2026-08-09T00:00:00+00:00",
            )
        )
        with (
            mock.patch.object(
                controller, "_all_listeners", return_value=_empty_listeners()
            ),
            self.assertRaisesRegex(devctl.DevctlError, "ownership mismatch"),
        ):
            controller.down()
        self.assertIsNone(
            process.poll(), "PID mismatch must be a refusal, never a kill"
        )

    def test_http_json_probe_requires_semantic_payload_not_status_alone(self) -> None:
        controller = self.controller()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=(sys.executable, "-c", "pass"),
            health=(),
        )
        health = devctl.HealthSpec(
            port_env="PORT_0",
            kind="http-json",
            path="/readyz",
            expect_status=200,
            expect={"service": "api", "status": "ready"},
        )
        with (
            mock.patch.object(
                controller,
                "_http_get",
                return_value=(200, {"content-type": "application/json"}, b"{}"),
            ),
            self.assertRaisesRegex(devctl.DevctlError, "semantic readiness"),
        ):
            controller._probe(service, health, devctl.PORT_SPECS)
        with mock.patch.object(
            controller,
            "_http_get",
            return_value=(
                200,
                {"content-type": "application/json; charset=utf-8"},
                b'{"service":"api","status":"ready","database":"ready"}',
            ),
        ):
            controller._probe(service, health, devctl.PORT_SPECS)

    def test_listener_ownership_requires_live_record_and_expected_process_group(
        self,
    ) -> None:
        direct = _record()
        delegated = _record(
            "minio", pid=5000, ports=(4176, 4177), ownership="delegated"
        )
        direct_listener = devctl.Listener(4170, 4242, "api", "127.0.0.1:4170")
        child_listener = devctl.Listener(4170, 4243, "api-child", "127.0.0.1:4170")
        delegated_listener = devctl.Listener(4176, 9000, "docker", "127.0.0.1:4176")
        with mock.patch(
            "scripts.devctl.process_identity", return_value="owned-process"
        ):
            self.assertEqual(
                devctl.DevController._listener_owner(direct_listener, {"api": direct}),
                direct,
            )
            with mock.patch("scripts.devctl.os.getpgid", return_value=direct.pid):
                self.assertEqual(
                    devctl.DevController._listener_owner(
                        child_listener, {"api": direct}
                    ),
                    direct,
                )
            with mock.patch(
                "scripts.devctl.os.getpgid", side_effect=PermissionError("denied")
            ):
                self.assertIsNone(
                    devctl.DevController._listener_owner(
                        child_listener, {"api": direct}
                    )
                )
            self.assertEqual(
                devctl.DevController._listener_owner(
                    delegated_listener,
                    {"minio": delegated},
                    frozenset({("minio", 4176)}),
                ),
                delegated,
            )
            self.assertIsNone(
                devctl.DevController._listener_owner(
                    delegated_listener, {"minio": delegated}
                )
            )
        with mock.patch("scripts.devctl.process_identity", return_value=None):
            self.assertIsNone(
                devctl.DevController._listener_owner(direct_listener, {"api": direct})
            )

        controller = self.controller()
        with mock.patch("scripts.devctl.process_identity", return_value=None):
            self.assertIsNone(
                controller._inspect_record_identity(direct, announce=True)
            )
        self.assertIn("STALE service=api", self.output[-1])
        with mock.patch("scripts.devctl.process_identity", return_value="reused"):
            self.assertIn(
                "PID reuse",
                controller._inspect_record_identity(direct, announce=False) or "",
            )

    def test_orphaned_compose_recovery_stops_only_exact_scoped_services(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        config = devctl.DevConfig(
            (
                devctl.ServiceSpec(
                    "postgis",
                    ("PORT_5",),
                    ("runner",),
                    (),
                    listener_ownership="delegated",
                ),
                devctl.ServiceSpec(
                    "minio",
                    ("PORT_6", "PORT_7"),
                    ("runner",),
                    (),
                    listener_ownership="delegated",
                ),
            )
        )
        stale = _record("postgis", pid=5001, ports=(4175,), ownership="delegated")
        controller._write_record(stale)
        records = {"postgis": stale}
        running = {
            "catalog": mock.MagicMock(spec=devctl.ComposeServiceRecord),
            "minio": mock.MagicMock(spec=devctl.ComposeServiceRecord),
        }
        running["catalog"].container_id = "c" * 64
        running["minio"].container_id = "d" * 64
        with (
            mock.patch.object(
                controller, "_running_compose_records", return_value=running
            ),
            mock.patch.object(controller, "_record_is_live", return_value=False),
            mock.patch.object(controller, "_command_digest", return_value="0" * 64),
            mock.patch.object(
                controller, "_run_scoped_compose", return_value=""
            ) as run,
        ):
            errors = controller._reconcile_orphaned_delegates(
                config, devctl.PORT_SPECS, records
            )
        self.assertEqual(
            [call.args[0] for call in run.call_args_list],
            [("stop", "--timeout", "3", "catalog")],
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("minio has no devctl ownership record", errors[0])
        self.assertEqual(records, {})
        self.assertFalse(controller._record_path("postgis").exists())

    def test_orphan_recovery_refuses_same_project_with_foreign_provenance(
        self,
    ) -> None:
        controller = self.controller()
        catalog = {
            "Project": devctl.PROJECT_NAME,
            "Service": "catalog",
            "State": "running",
            "Name": f"{devctl.PROJECT_NAME}-catalog-1",
            "ID": "c" * 64,
            "Labels": _compose_labels(controller.root, "catalog").replace(
                str(controller.root / "compose.yaml"), "/foreign/compose.yaml"
            ),
            "Publishers": [
                {
                    "URL": "127.0.0.1",
                    "PublishedPort": 4175,
                    "TargetPort": 5432,
                    "Protocol": "tcp",
                }
            ],
        }
        hashes = f"catalog {'a' * 64}\nminio {'b' * 64}\n"
        with (
            mock.patch.object(
                controller,
                "_run_scoped_compose",
                side_effect=[json.dumps(catalog), hashes],
            ),
            self.assertRaisesRegex(devctl.DevctlError, "provenance mismatch"),
        ):
            controller._running_compose_records()

    def test_orphan_recovery_reports_record_removal_failure(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        config = devctl.DevConfig(
            (
                devctl.ServiceSpec(
                    "postgis",
                    ("PORT_5",),
                    ("runner",),
                    (),
                    listener_ownership="delegated",
                ),
                devctl.ServiceSpec(
                    "minio",
                    ("PORT_6", "PORT_7"),
                    ("runner",),
                    (),
                    listener_ownership="delegated",
                ),
            )
        )
        stale = _record("postgis", pid=5001, ports=(4175,), ownership="delegated")
        controller._write_record(stale)
        records = {"postgis": stale}
        with (
            mock.patch.object(
                controller,
                "_running_compose_records",
                return_value={
                    "catalog": devctl.ComposeServiceRecord(
                        container_id="c" * 64,
                        state="running",
                        name=f"{devctl.PROJECT_NAME}-catalog-1",
                        publishers=frozenset(),
                        labels={},
                    )
                },
            ),
            mock.patch.object(controller, "_record_is_live", return_value=False),
            mock.patch.object(controller, "_command_digest", return_value="0" * 64),
            mock.patch.object(controller, "_run_scoped_compose", return_value=""),
            mock.patch.object(Path, "unlink", side_effect=OSError("denied")),
        ):
            errors = controller._reconcile_orphaned_delegates(
                config, devctl.PORT_SPECS, records
            )

        self.assertEqual(len(errors), 1)
        self.assertIn("cannot remove reconciled PID record for postgis", errors[0])
        self.assertEqual(records, {"postgis": stale})

    def test_orphan_recovery_refuses_recreated_container_instance(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        config = devctl.DevConfig(
            (
                devctl.ServiceSpec(
                    "postgis",
                    ("PORT_5",),
                    ("runner",),
                    (),
                    listener_ownership="delegated",
                ),
                devctl.ServiceSpec(
                    "minio",
                    ("PORT_6", "PORT_7"),
                    ("runner",),
                    (),
                    listener_ownership="delegated",
                ),
            )
        )
        stale = _record(
            "postgis",
            pid=5001,
            ports=(4175,),
            ownership="delegated",
        )
        records = {"postgis": stale}
        recreated = devctl.ComposeServiceRecord(
            container_id="e" * 64,
            state="running",
            name=f"{devctl.PROJECT_NAME}-catalog-1",
            publishers=frozenset(),
            labels={},
        )
        with (
            mock.patch.object(
                controller,
                "_running_compose_records",
                return_value={"catalog": recreated},
            ),
            mock.patch.object(controller, "_record_is_live", return_value=False),
            mock.patch.object(controller, "_command_digest", return_value="0" * 64),
            mock.patch.object(controller, "_run_scoped_compose") as stop,
        ):
            errors = controller._reconcile_orphaned_delegates(
                config, devctl.PORT_SPECS, records
            )

        stop.assert_not_called()
        self.assertEqual(len(errors), 1)
        self.assertIn("is not bound to running container catalog", errors[0])
        self.assertEqual(records, {"postgis": stale})

    def test_delegated_container_binding_is_persisted_before_health(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        postgis = dataclasses.replace(
            _record("postgis", ports=(4175,), ownership="delegated"),
            delegated_container_id=None,
        )
        minio = dataclasses.replace(
            _record(
                "minio",
                ports=(4176, 4177),
                ownership="delegated",
            ),
            delegated_container_id=None,
        )
        records = {"postgis": postgis, "minio": minio}
        publishers = {
            "catalog": devctl.ComposeServiceRecord(
                container_id="c" * 64,
                state="running",
                name=f"{devctl.PROJECT_NAME}-catalog-1",
                publishers=frozenset(),
                labels={},
            ),
            "minio": devctl.ComposeServiceRecord(
                container_id="d" * 64,
                state="running",
                name=f"{devctl.PROJECT_NAME}-minio-1",
                publishers=frozenset(),
                labels={},
            ),
        }
        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            mock.patch.object(controller, "_compose_ps_output", return_value="{}"),
            mock.patch(
                "scripts.devctl.parse_compose_ps_publishers",
                return_value=publishers,
            ),
            mock.patch.object(
                controller,
                "_compose_config_hashes",
                return_value={"catalog": "a" * 64, "minio": "b" * 64},
            ),
            mock.patch.object(
                controller, "_verify_delegated_publishers", return_value=set()
            ),
            mock.patch.object(
                controller, "_write_record", wraps=controller._write_record
            ) as write,
        ):
            controller._bind_delegated_containers(records)

        self.assertEqual(write.call_count, 2)
        self.assertEqual(records["postgis"].delegated_container_id, "c" * 64)
        self.assertEqual(records["minio"].delegated_container_id, "d" * 64)
        loaded = controller._load_records()
        self.assertEqual(loaded["postgis"].delegated_container_id, "c" * 64)
        self.assertEqual(loaded["minio"].delegated_container_id, "d" * 64)

    def test_inventory_announces_free_ports_and_aggregates_listener_refusals(
        self,
    ) -> None:
        controller = self.controller()
        listeners = _empty_listeners()
        listeners[4170] = [devctl.Listener(4170, 99, "foreign", "*:4170")]
        with (
            mock.patch.object(controller, "_all_listeners", return_value=listeners),
            mock.patch("scripts.devctl.process_identity", return_value=None),
        ):
            returned, errors = controller._inventory({}, announce=True)
        self.assertIs(returned, listeners)
        self.assertTrue(any("not 127.0.0.1" in error for error in errors))
        self.assertTrue(any("foreign holder" in error for error in errors))
        self.assertTrue(any(line.startswith("FREE port=4171") for line in self.output))
        self.assertTrue(any(line.startswith("HELD port=4170") for line in self.output))

    def test_environment_expansion_is_scoped_and_rejects_unresolved_values(
        self,
    ) -> None:
        controller = self.controller(
            INHERITED="dropped",
            PYTHONPATH="/foreign/injected",
            COMPOSE_FILE="/foreign/compose.yaml",
            NODE_OPTIONS="--require=/foreign/injected.cjs",
            PATH="/trusted/bin",
        )
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("server", "--host", "${HOST}", "--port", "${PORT_0}"),
            health=(),
            environment={"CUSTOM": "${DEVCTL_SERVICE}:${PORT}"},
        )
        env = controller._service_environment(service, devctl.PORT_SPECS)
        self.assertEqual(env["HOST"], "127.0.0.1")
        self.assertEqual(env["PORT"], "4170")
        self.assertEqual(env["CUSTOM"], "api:4170")
        self.assertEqual(env["PATH"], "/trusted/bin")
        for unsafe in ("INHERITED", "PYTHONPATH", "COMPOSE_FILE", "NODE_OPTIONS"):
            self.assertNotIn(unsafe, env)
        self.assertEqual(env["HOME"], str(controller.home_dir))
        self.assertEqual(env["DOCKER_CONFIG"], str(controller.config_dir / "docker"))
        self.assertEqual(
            controller._runtime_argv(service, env),
            ("server", "--host", "127.0.0.1", "--port", "4170"),
        )
        digest = controller._command_digest(
            controller._runtime_argv(service, env), env, service
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        changed_env = dict(env)
        changed_env["GATEWAYGS_DEPENDENCY_TIMEOUT_SECONDS"] = "2.0"
        self.assertNotEqual(
            digest,
            controller._command_digest(
                controller._runtime_argv(service, changed_env), changed_env, service
            ),
        )
        with self.assertRaisesRegex(devctl.DevctlError, "unresolved/invalid"):
            controller._expand("${MISSING}", env, "value")
        with self.assertRaisesRegex(devctl.DevctlError, "unresolved/invalid"):
            controller._expand("${", env, "value")

    def test_duration_and_identity_guards_cover_numeric_range_and_pid_reuse(
        self,
    ) -> None:
        controller = self.controller(BAD="text", LOW="0", VALID="1.5")
        with self.assertRaisesRegex(devctl.DevctlError, "must be numeric"):
            controller._duration_env("BAD", 1, 0.1, 2)
        with self.assertRaisesRegex(devctl.DevctlError, "must be between"):
            controller._duration_env("LOW", 1, 0.1, 2)
        self.assertEqual(controller._duration_env("VALID", 1, 0.1, 2), 1.5)
        record = _record()
        devctl.DevController._require_identity(record, record.identity, "signal")
        with self.assertRaisesRegex(devctl.DevctlError, "ownership mismatch"):
            devctl.DevController._require_identity(record, "reused", "signal")

    def test_start_service_refuses_spawn_failure_and_unidentifiable_child(self) -> None:
        controller = self.controller(DEVCTL_STARTUP_GRACE_SECONDS="0")
        controller._ensure_layout()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("missing-command",),
            health=(),
        )
        with (
            mock.patch(
                "scripts.devctl.subprocess.Popen", side_effect=OSError("missing")
            ),
            self.assertRaisesRegex(devctl.DevctlError, "cannot start api"),
        ):
            controller._start_service(service, devctl.PORT_SPECS)

        process = mock.MagicMock(pid=99991)
        process.poll.return_value = 7
        with (
            mock.patch("scripts.devctl.subprocess.Popen", return_value=process),
            mock.patch("scripts.devctl.process_identity", return_value=None),
            mock.patch("scripts.devctl.os.kill") as kill,
            self.assertRaisesRegex(devctl.DevctlError, "before a process identity"),
        ):
            controller._start_service(service, devctl.PORT_SPECS)
        kill.assert_called_once_with(process.pid, signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=1)
        self.assertNotIn(process.pid, controller._children)

    def test_start_service_refuses_nonregular_log_without_spawning(self) -> None:
        controller = self.controller(DEVCTL_STARTUP_GRACE_SECONDS="0")
        controller._ensure_layout()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("server",),
            health=(),
        )
        log_path = controller.logs_dir / "api.log"
        os.mkfifo(log_path, mode=0o600)

        with (
            mock.patch("scripts.devctl.subprocess.Popen") as spawn,
            self.assertRaisesRegex(devctl.DevctlError, "cannot open service log"),
        ):
            controller._start_service(service, devctl.PORT_SPECS)
        spawn.assert_not_called()

    def test_start_service_repairs_existing_log_permissions(self) -> None:
        controller = self.controller(DEVCTL_STARTUP_GRACE_SECONDS="0")
        controller._ensure_layout()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("server",),
            health=(),
        )
        log_path = controller.logs_dir / "api.log"
        log_path.write_bytes(b"")
        log_path.chmod(0o644)
        process = mock.MagicMock(pid=99994)
        process.poll.return_value = 1
        with (
            mock.patch("scripts.devctl.subprocess.Popen", return_value=process),
            mock.patch("scripts.devctl.process_identity", return_value=None),
            mock.patch("scripts.devctl.os.kill"),
            self.assertRaisesRegex(devctl.DevctlError, "before a process identity"),
        ):
            controller._start_service(service, devctl.PORT_SPECS)
        self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)

    def test_start_service_removes_record_when_child_exits_during_grace(self) -> None:
        controller = self.controller(DEVCTL_STARTUP_GRACE_SECONDS="0")
        controller._ensure_layout()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("server",),
            health=(),
        )
        process = mock.MagicMock(pid=99992)
        process.poll.side_effect = [None, 1, 1]
        with (
            mock.patch("scripts.devctl.subprocess.Popen", return_value=process),
            mock.patch("scripts.devctl.process_identity", return_value="identity"),
            mock.patch.object(controller, "_write_record") as write_record,
            self.assertRaisesRegex(devctl.DevctlError, "exited during startup"),
        ):
            controller._start_service(service, devctl.PORT_SPECS)
        write_record.assert_called_once()
        self.assertNotIn(process.pid, controller._children)

    def test_start_service_cleans_owned_child_when_record_persistence_fails(
        self,
    ) -> None:
        controller = self.controller(DEVCTL_STARTUP_GRACE_SECONDS="0")
        controller._ensure_layout()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("server",),
            health=(),
        )
        process = mock.MagicMock(pid=99993)
        process.poll.return_value = None
        identities = iter(["identity", "identity", None])
        with (
            mock.patch("scripts.devctl.subprocess.Popen", return_value=process),
            mock.patch(
                "scripts.devctl.process_identity",
                side_effect=lambda _pid: next(identities),
            ),
            mock.patch.object(
                controller, "_write_record", side_effect=OSError("disk full")
            ),
            mock.patch("scripts.devctl.os.kill") as kill,
            self.assertRaisesRegex(devctl.DevctlError, "cannot persist PID ownership"),
        ):
            controller._start_service(service, devctl.PORT_SPECS)
        kill.assert_called_once_with(process.pid, signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=2)
        self.assertNotIn(process.pid, controller._children)
        self.assertFalse(controller._record_path("api").exists())
        self.assertFalse(
            controller._record_path("api").with_suffix(".json.tmp").exists()
        )

    def test_start_service_rolls_back_when_record_temporary_is_fifo(self) -> None:
        controller = self.controller(DEVCTL_STARTUP_GRACE_SECONDS="0")
        controller._ensure_layout()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("server",),
            health=(),
        )
        temporary = controller._record_path("api").with_suffix(".json.tmp")
        os.mkfifo(temporary, mode=0o600)
        process = mock.MagicMock(pid=99995)
        process.poll.return_value = None
        identities = iter(["identity", "identity", None])
        with (
            mock.patch("scripts.devctl.subprocess.Popen", return_value=process),
            mock.patch(
                "scripts.devctl.process_identity",
                side_effect=lambda _pid: next(identities),
            ),
            mock.patch("scripts.devctl.os.kill") as kill,
            self.assertRaisesRegex(devctl.DevctlError, "cannot persist PID ownership"),
        ):
            controller._start_service(service, devctl.PORT_SPECS)
        kill.assert_called_once_with(process.pid, signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=2)
        self.assertNotIn(process.pid, controller._children)
        self.assertFalse(temporary.exists())

    def test_wait_and_termination_escalation_only_signal_owned_pid(self) -> None:
        controller = self.controller(DEVCTL_SHUTDOWN_TIMEOUT_SECONDS="0.1")
        controller._ensure_layout()
        record = _record()
        controller._write_record(record)
        with mock.patch("scripts.devctl.process_identity", return_value=None):
            controller._terminate_record(record, remove_record=True)
        self.assertFalse(controller._record_path(record.service).exists())
        self.assertIn("already-exited=true", self.output[-1])

        controller._write_record(record)
        with (
            mock.patch("scripts.devctl.process_identity", return_value=record.identity),
            mock.patch.object(
                controller, "_wait_until_stopped", side_effect=[False, True]
            ),
            mock.patch("scripts.devctl.os.kill") as kill,
        ):
            controller._terminate_record(record, remove_record=True)
        self.assertEqual(
            kill.call_args_list,
            [
                mock.call(record.pid, signal.SIGTERM),
                mock.call(record.pid, signal.SIGKILL),
            ],
        )

        with (
            mock.patch("scripts.devctl.process_identity", return_value=record.identity),
            mock.patch.object(controller, "_wait_until_stopped", return_value=False),
            mock.patch("scripts.devctl.os.kill"),
            self.assertRaisesRegex(devctl.DevctlError, "did not stop"),
        ):
            controller._terminate_record(record, remove_record=False)

    def test_wait_until_stopped_refuses_identity_change_and_reports_timeout(
        self,
    ) -> None:
        record = _record()
        ticks = iter([0.0, 0.01])
        with (
            mock.patch(
                "scripts.devctl.time.monotonic", side_effect=lambda: next(ticks)
            ),
            mock.patch("scripts.devctl.process_identity", return_value=None),
        ):
            self.assertTrue(devctl.DevController._wait_until_stopped(record, 1))

        ticks = iter([0.0, 0.01])
        with (
            mock.patch(
                "scripts.devctl.time.monotonic", side_effect=lambda: next(ticks)
            ),
            mock.patch("scripts.devctl.process_identity", return_value="reused"),
            self.assertRaisesRegex(devctl.DevctlError, "ownership mismatch"),
        ):
            devctl.DevController._wait_until_stopped(record, 1)

        ticks = iter([0.0, 1.0])
        with mock.patch(
            "scripts.devctl.time.monotonic", side_effect=lambda: next(ticks)
        ):
            self.assertFalse(devctl.DevController._wait_until_stopped(record, 0.5))

    def test_finish_stop_reports_unreaped_owned_child(self) -> None:
        controller = self.controller()
        controller._ensure_layout()
        record = _record()
        child = mock.MagicMock()
        child.wait.side_effect = subprocess.TimeoutExpired(["child"], 2)
        controller._children[record.pid] = child
        with self.assertRaisesRegex(devctl.DevctlError, "was not reaped"):
            controller._finish_stop(record, remove_record=False, already_exited=False)
        self.assertIs(controller._children[record.pid], child)

    def test_reconcile_refuses_unknown_or_drifted_records_and_removes_stale(
        self,
    ) -> None:
        controller = self.controller()
        controller._ensure_layout()
        service = devctl.ServiceSpec(
            name="api",
            port_envs=("PORT_0",),
            command=("server", "${PORT_0}"),
            health=(),
        )
        config = devctl.DevConfig((service,))
        with self.assertRaisesRegex(
            devctl.DevctlError, "not present in current config"
        ):
            controller._reconcile_existing(
                config, devctl.PORT_SPECS, {"foreign": _record("foreign")}
            )

        stale = _record()
        controller._write_record(stale)
        stale_records = {"api": stale}
        with mock.patch.object(controller, "_record_is_live", return_value=False):
            controller._reconcile_existing(config, devctl.PORT_SPECS, stale_records)
        self.assertEqual(stale_records, {})
        self.assertFalse(controller._record_path("api").exists())

        env = controller._service_environment(service, devctl.PORT_SPECS)
        argv = controller._runtime_argv(service, env)
        matching = devctl.ProcessRecord(
            service="api",
            pid=4242,
            identity="owned-process",
            command_digest=controller._command_digest(argv, env, service),
            ports=(4170,),
            listener_ownership="direct",
            started_at="now",
        )
        with mock.patch.object(controller, "_record_is_live", return_value=True):
            controller._reconcile_existing(config, devctl.PORT_SPECS, {"api": matching})
        self.assertIn("RUNNING service=api", self.output[-1])

        drifted = dataclasses.replace(matching, command_digest="f" * 64)
        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            self.assertRaisesRegex(devctl.DevctlError, "does not match current config"),
        ):
            controller._reconcile_existing(config, devctl.PORT_SPECS, {"api": drifted})

    def test_start_missing_clean_inventory_and_rollback_are_targeted(self) -> None:
        controller = self.controller()
        service_a = devctl.ServiceSpec("api", ("PORT_0",), ("api",), ())
        service_b = devctl.ServiceSpec("web", ("PORT_1",), ("web",), ())
        config = devctl.DevConfig((service_a, service_b))
        existing = _record()
        new = _record("web", ports=(4171,))
        records = {"api": existing}
        started: list[devctl.ProcessRecord] = []
        with mock.patch.object(controller, "_start_service", return_value=new) as start:
            controller._start_missing(config, devctl.PORT_SPECS, records, started)
        self.assertEqual(started, [new])
        start.assert_called_once_with(service_b, devctl.PORT_SPECS)

        with (
            mock.patch.object(
                controller, "_inventory", return_value=(_empty_listeners(), ["unsafe"])
            ),
            self.assertRaisesRegex(devctl.DevctlError, "post-start ownership"),
        ):
            controller._require_clean_inventory(records)

        with mock.patch.object(
            controller,
            "_terminate_record",
            side_effect=[devctl.DevctlError("already gone"), None],
        ) as terminate:
            errors = controller._rollback_started([existing, new])
        self.assertEqual(errors, ["web: already gone"])
        self.assertEqual(
            terminate.call_args_list,
            [
                mock.call(new, remove_record=True),
                mock.call(existing, remove_record=True),
            ],
        )

    def test_up_reports_startup_and_forced_rollback_failure(self) -> None:
        controller = self.controller()
        config = devctl.DevConfig(
            (devctl.ServiceSpec("api", ("PORT_0",), ("api",), ()),)
        )
        started = _record()
        primary = devctl.DevctlError("unsafe post-start inventory")

        def collect_started(
            _config: devctl.DevConfig,
            _ports: dict[str, int],
            _records: dict[str, devctl.ProcessRecord],
            collected: list[devctl.ProcessRecord],
        ) -> None:
            collected.append(started)

        with (
            mock.patch.object(controller, "_ensure_layout"),
            mock.patch.object(controller, "_lock") as lifecycle_lock,
            mock.patch.object(
                controller,
                "_common_preflight",
                return_value=(devctl.PORT_SPECS, {}),
            ),
            mock.patch("scripts.devctl.load_config", return_value=config),
            mock.patch.object(controller, "_reconcile_existing"),
            mock.patch.object(
                controller, "_start_missing", side_effect=collect_started
            ),
            mock.patch.object(
                controller, "_require_clean_inventory", side_effect=primary
            ),
            mock.patch.object(
                controller,
                "_rollback_started",
                return_value=["api: signal refused"],
            ),
            self.assertRaisesRegex(
                devctl.DevctlError, "startup failed.*rollback also failed"
            ) as raised,
        ):
            lifecycle_lock.return_value.__enter__.return_value = None
            controller.up()
        self.assertIs(raised.exception.__cause__, primary)

    def test_up_rolls_back_services_collected_before_mid_start_failure(self) -> None:
        controller = self.controller()
        config = devctl.DevConfig(
            (
                devctl.ServiceSpec("api", ("PORT_0",), ("api",), ()),
                devctl.ServiceSpec("web", ("PORT_1",), ("web",), ()),
            )
        )
        first = _record()
        failure = devctl.DevctlError("second service failed")

        def fail_after_first(
            _config: devctl.DevConfig,
            _ports: dict[str, int],
            _records: dict[str, devctl.ProcessRecord],
            collected: list[devctl.ProcessRecord],
        ) -> None:
            collected.append(first)
            raise failure

        with (
            mock.patch.object(controller, "_ensure_layout"),
            mock.patch.object(controller, "_lock") as lifecycle_lock,
            mock.patch.object(
                controller,
                "_common_preflight",
                return_value=(devctl.PORT_SPECS, {}),
            ),
            mock.patch("scripts.devctl.load_config", return_value=config),
            mock.patch.object(controller, "_reconcile_existing"),
            mock.patch.object(
                controller, "_start_missing", side_effect=fail_after_first
            ),
            mock.patch.object(
                controller, "_rollback_started", return_value=[]
            ) as rollback,
            self.assertRaisesRegex(devctl.DevctlError, "second service failed"),
        ):
            lifecycle_lock.return_value.__enter__.return_value = None
            controller.up()
        rollback.assert_called_once_with([first])

    def test_down_no_records_and_foreign_only_paths_never_signal(self) -> None:
        controller = self.controller()
        with mock.patch.object(
            controller, "_all_listeners", return_value=_empty_listeners()
        ):
            controller.down()
        self.assertIn("no owned services", self.output[-1])

        foreign = _empty_listeners()
        foreign[4179] = [devctl.Listener(4179, 8000, "foreign", "127.0.0.1:4179")]
        with (
            mock.patch.object(controller, "_all_listeners", return_value=foreign),
            mock.patch("scripts.devctl.os.kill") as kill,
            self.assertRaisesRegex(devctl.DevctlError, "foreign/unsafe holders"),
        ):
            controller.down()
        kill.assert_not_called()

    def test_stop_release_timeout_and_remaining_listener_reporting(self) -> None:
        controller = self.controller(DEVCTL_SHUTDOWN_TIMEOUT_SECONDS="0.1")
        controller._ensure_layout()
        record = _record()
        with mock.patch.object(
            controller,
            "_terminate_record",
            side_effect=PermissionError("denied"),
        ):
            self.assertEqual(controller._stop_and_release(record), ["denied"])

        held = _empty_listeners()
        held[4170] = [devctl.Listener(4170, 4242, "api", "127.0.0.1:4170")]
        ticks = iter([0.0, 0.01, 0.11])
        with (
            mock.patch.object(controller, "_terminate_record"),
            mock.patch.object(controller, "_all_listeners", return_value=held),
            mock.patch(
                "scripts.devctl.time.monotonic", side_effect=lambda: next(ticks)
            ),
            mock.patch("scripts.devctl.time.sleep"),
        ):
            errors = controller._stop_and_release(record)
        self.assertIn("listeners remained", errors[0])
        self.assertIn("4170/pid=4242", errors[0])
        self.assertEqual(
            controller._remaining_listener_errors(held),
            ["port 4170 remains held by pid=4242 command='api'; not killed"],
        )

    def test_json_contains_handles_nested_subset_and_exact_lists(self) -> None:
        actual = {"service": "api", "nested": {"ready": True}, "items": [1, 2]}
        self.assertTrue(
            devctl.DevController._json_contains(
                actual, {"nested": {"ready": True}, "items": [1, 2]}
            )
        )
        self.assertFalse(devctl.DevController._json_contains(actual, {"missing": True}))
        self.assertFalse(devctl.DevController._json_contains([1, 2], [2, 1]))
        self.assertTrue(devctl.DevController._json_contains("ready", "ready"))

    def test_http_get_bounds_body_disables_redirects_and_normalizes_errors(
        self,
    ) -> None:
        controller = self.controller()
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers.items.return_value = [("Content-Type", "application/json")]
        response.read.return_value = b"{}"
        opener = mock.MagicMock()
        opener.open.return_value = response
        with mock.patch(
            "scripts.devctl.urllib.request.build_opener", return_value=opener
        ):
            self.assertEqual(
                controller._http_get("http://127.0.0.1:4170/ready", 1),
                (200, {"content-type": "application/json"}, b"{}"),
            )
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")

        response.read.return_value = b"x" * (devctl.MAX_HEALTH_BODY_BYTES + 1)
        with (
            mock.patch(
                "scripts.devctl.urllib.request.build_opener", return_value=opener
            ),
            self.assertRaisesRegex(devctl.DevctlError, "exceeded 64 KiB"),
        ):
            controller._http_get("http://127.0.0.1:4170/ready", 1)

        error_headers = Message()
        error_headers["Retry-After"] = "1"
        http_error = urllib.error.HTTPError(
            "http://127.0.0.1:4170/ready",
            503,
            "unavailable",
            error_headers,
            io.BytesIO(),
        )
        opener.open.side_effect = http_error
        with mock.patch(
            "scripts.devctl.urllib.request.build_opener", return_value=opener
        ):
            status, headers, body = controller._http_get(
                "http://127.0.0.1:4170/ready", 1
            )
        self.assertEqual((status, headers, body), (503, {"retry-after": "1"}, b""))
        opener.open.side_effect = None
        http_error.close()

        opener.open.side_effect = urllib.error.URLError("refused")
        with (
            mock.patch(
                "scripts.devctl.urllib.request.build_opener", return_value=opener
            ),
            self.assertRaisesRegex(devctl.DevctlError, "HTTP readiness request failed"),
        ):
            controller._http_get("http://127.0.0.1:4170/ready", 1)

    def test_command_json_probe_covers_success_timeout_exit_size_and_payload_refusal(
        self,
    ) -> None:
        controller = self.controller()
        service = devctl.ServiceSpec("api", ("PORT_0",), ("server",), ())
        health = devctl.HealthSpec(
            port_env="PORT_0",
            kind="command-json",
            expect={"service": "api", "status": "ready"},
            argv=(sys.executable, "probe-${PORT_0}"),
            timeout_seconds=1,
        )
        success = subprocess.CompletedProcess(
            ["probe"], 0, stdout=b'{"service":"api","status":"ready"}', stderr=b""
        )
        with mock.patch("scripts.devctl.subprocess.run", return_value=success) as run:
            controller._probe_command_json(service, health, devctl.PORT_SPECS)
        self.assertEqual(run.call_args.args[0][-1], "probe-4170")

        failures: list[tuple[object, str]] = [
            (OSError("missing"), "readiness command failed"),
            (
                subprocess.TimeoutExpired(["probe"], 1),
                "readiness command failed",
            ),
            (
                subprocess.CompletedProcess(["probe"], 2, stdout=b"", stderr=b""),
                "exited 2",
            ),
            (
                subprocess.CompletedProcess(
                    ["probe"],
                    0,
                    stdout=b"x" * (devctl.MAX_HEALTH_BODY_BYTES + 1),
                    stderr=b"",
                ),
                "exceeded 64 KiB",
            ),
            (
                subprocess.CompletedProcess(
                    ["probe"], 0, stdout=b"not-json", stderr=b""
                ),
                "is not JSON",
            ),
            (
                subprocess.CompletedProcess(["probe"], 0, stdout=b"{}", stderr=b""),
                "did not match",
            ),
        ]
        for result, expected in failures:
            patcher = (
                mock.patch("scripts.devctl.subprocess.run", side_effect=result)
                if isinstance(result, BaseException)
                else mock.patch("scripts.devctl.subprocess.run", return_value=result)
            )
            with (
                self.subTest(expected=expected),
                patcher,
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                controller._probe_command_json(service, health, devctl.PORT_SPECS)

    def test_http_probe_refuses_status_header_text_and_json_semantic_failures(
        self,
    ) -> None:
        controller = self.controller()
        service = devctl.ServiceSpec("api", ("PORT_0",), ("server",), ())
        with self.assertRaisesRegex(devctl.DevctlError, "internal HTTP"):
            controller._require_http_health(
                devctl.HealthSpec(port_env="PORT_0", kind="http-json")
            )

        json_health = devctl.HealthSpec(
            port_env="PORT_0",
            kind="http-json",
            path="/ready",
            expect_status=200,
            expect={"service": "api", "status": "ready"},
        )
        with (
            mock.patch.object(controller, "_http_get", return_value=(503, {}, b"")),
            self.assertRaisesRegex(devctl.DevctlError, "returned HTTP 503"),
        ):
            controller._probe_http(service, json_health, devctl.PORT_SPECS)

        ready_health = devctl.HealthSpec(
            port_env="PORT_0",
            kind="http-ready",
            path="/health/ready",
            expect_status=204,
            expect_headers={"x-ready": "yes"},
        )
        with (
            mock.patch.object(controller, "_http_get", return_value=(204, {}, b"")),
            self.assertRaisesRegex(devctl.DevctlError, "header 'x-ready'"),
        ):
            controller._probe_http(service, ready_health, devctl.PORT_SPECS)
        with mock.patch.object(
            controller,
            "_http_get",
            return_value=(204, {"x-ready": "yes"}, b"ignored"),
        ):
            controller._probe_http(service, ready_health, devctl.PORT_SPECS)

        text_health = devctl.HealthSpec(
            port_env="PORT_0",
            kind="http-text",
            path="/health",
            expect_status=200,
            expect_text="stable-ready-marker",
        )
        for body, expected in (
            (b"\xff", "not UTF-8"),
            (b"healthy but wrong", "marker was absent"),
        ):
            with (
                self.subTest(text_error=expected),
                mock.patch.object(
                    controller, "_http_get", return_value=(200, {}, body)
                ),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                controller._probe_http(service, text_health, devctl.PORT_SPECS)
        with mock.patch.object(
            controller,
            "_http_get",
            return_value=(200, {}, b"prefix stable-ready-marker suffix"),
        ):
            controller._probe_http(service, text_health, devctl.PORT_SPECS)

        json_failures = [
            ({}, b"{}", "not application/json"),
            (
                {"content-type": "application/json"},
                b"not-json",
                "not valid JSON",
            ),
            (
                {"content-type": "application/json"},
                b"{}",
                "did not match",
            ),
        ]
        for headers, body, expected in json_failures:
            with (
                self.subTest(json_error=expected),
                mock.patch.object(
                    controller,
                    "_http_get",
                    return_value=(200, headers, body),
                ),
                self.assertRaisesRegex(devctl.DevctlError, expected),
            ):
                controller._probe_http(service, json_health, devctl.PORT_SPECS)

    def test_health_record_validation_requires_exact_live_matching_runtime(
        self,
    ) -> None:
        controller = self.controller()
        service = devctl.ServiceSpec("api", ("PORT_0",), ("server", "${PORT_0}"), ())
        config = devctl.DevConfig((service,))
        with self.assertRaisesRegex(devctl.DevctlError, "missing=.*api"):
            controller._validate_health_records(
                config, devctl.PORT_SPECS, {"extra": _record("extra")}
            )

        record = _record()
        with (
            mock.patch.object(controller, "_record_is_live", return_value=False),
            self.assertRaisesRegex(devctl.DevctlError, "not owned/alive"),
        ):
            controller._validate_health_records(
                config, devctl.PORT_SPECS, {"api": record}
            )

        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            self.assertRaisesRegex(devctl.DevctlError, "runtime differs"),
        ):
            controller._validate_health_records(
                config, devctl.PORT_SPECS, {"api": record}
            )

        env = controller._service_environment(service, devctl.PORT_SPECS)
        matching = dataclasses.replace(
            record,
            command_digest=controller._command_digest(
                controller._runtime_argv(service, env), env, service
            ),
        )
        with mock.patch.object(controller, "_record_is_live", return_value=True):
            controller._validate_health_records(
                config, devctl.PORT_SPECS, {"api": matching}
            )

    def test_endpoint_pending_distinguishes_absent_foreign_failed_and_ready(
        self,
    ) -> None:
        controller = self.controller()
        service = devctl.ServiceSpec("api", ("PORT_0",), ("server",), ())
        health = devctl.HealthSpec(
            port_env="PORT_0",
            kind="http-json",
            path="/ready",
            expect_status=200,
            expect={"service": "api", "status": "ready"},
        )
        record = _record()
        records = {"api": record}
        self.assertEqual(
            controller._endpoint_pending_reason(
                service, health, records, _empty_listeners()
            ),
            "no listening socket yet",
        )

        foreign = _empty_listeners()
        foreign[4170] = [devctl.Listener(4170, 9000, "foreign", "*:4170")]
        with self.assertRaisesRegex(devctl.DevctlError, "unsafe/foreign listener"):
            controller._endpoint_pending_reason(service, health, records, foreign)

        owned = _empty_listeners()
        owned[4170] = [devctl.Listener(4170, record.pid, "api", "127.0.0.1:4170")]
        with (
            mock.patch.object(controller, "_listener_owner", return_value=record),
            mock.patch.object(
                controller, "_probe", side_effect=devctl.DevctlError("warming")
            ),
        ):
            self.assertEqual(
                controller._endpoint_pending_reason(service, health, records, owned),
                "warming",
            )
        with (
            mock.patch.object(controller, "_listener_owner", return_value=record),
            mock.patch.object(controller, "_probe"),
        ):
            self.assertIsNone(
                controller._endpoint_pending_reason(service, health, records, owned)
            )

    def test_health_pass_refuses_process_exit_and_collects_pending_endpoints(
        self,
    ) -> None:
        controller = self.controller()
        health = devctl.HealthSpec("PORT_0", "command-json")
        service = devctl.ServiceSpec("api", ("PORT_0",), ("server",), (health,))
        config = devctl.DevConfig((service,))
        record = _record()
        with (
            mock.patch.object(controller, "_record_is_live", return_value=False),
            self.assertRaisesRegex(devctl.DevctlError, "exited while waiting"),
        ):
            controller._health_pass(config, devctl.PORT_SPECS, {"api": record})

        with (
            mock.patch.object(controller, "_record_is_live", return_value=True),
            mock.patch.object(
                controller, "_all_listeners", return_value=_empty_listeners()
            ),
        ):
            self.assertEqual(
                controller._health_pass(config, devctl.PORT_SPECS, {"api": record}),
                {"api:4170": "no listening socket yet"},
            )

    def test_health_loop_emits_semantic_ready_and_times_out_with_reason(self) -> None:
        controller = self.controller(
            DEVCTL_HEALTH_TIMEOUT_SECONDS="0.05",
            DEVCTL_HEALTH_INTERVAL_SECONDS="0.01",
        )
        controller._ensure_layout()
        self.write_config()
        config = devctl.load_config(controller.config_path)
        records = {
            service.name: _record(
                service.name,
                pid=5000 + index,
                ports=tuple(devctl.PORT_SPECS[key] for key in service.port_envs),
                ownership=service.listener_ownership,
            )
            for index, service in enumerate(config.services)
        }
        with (
            mock.patch.object(controller, "_load_records", return_value=records),
            mock.patch.object(controller, "_validate_health_records"),
            mock.patch.object(controller, "_health_pass", return_value={}),
        ):
            controller.health()
        self.assertIn("HEALTH OK", self.output[-1])
        self.assertEqual(
            sum(line.startswith("READY service=") for line in self.output), 7
        )

        ticks = iter([0.0, 0.06])
        with (
            mock.patch.object(controller, "_load_records", return_value=records),
            mock.patch.object(controller, "_validate_health_records"),
            mock.patch.object(
                controller,
                "_health_pass",
                return_value={"api:4170": "not ready"},
            ),
            mock.patch(
                "scripts.devctl.time.monotonic", side_effect=lambda: next(ticks)
            ),
            self.assertRaisesRegex(devctl.DevctlError, "semantic readiness timed out"),
        ):
            controller.health()

    def test_main_maps_safe_failures_and_interrupts_to_exit_codes(self) -> None:
        self.assertEqual(devctl.main(["preflight", "--root", str(self.root)]), 1)

        controller = mock.MagicMock()
        controller.preflight.side_effect = devctl.DevctlError("safe refusal")
        with mock.patch("scripts.devctl.DevController", return_value=controller):
            self.assertEqual(devctl.main(["preflight"]), 1)

        controller.preflight.side_effect = KeyboardInterrupt
        with mock.patch("scripts.devctl.DevController", return_value=controller):
            self.assertEqual(devctl.main(["preflight"]), 130)

        controller.preflight.side_effect = None
        with mock.patch("scripts.devctl.DevController", return_value=controller):
            self.assertEqual(devctl.main(["preflight"]), 0)


if __name__ == "__main__":
    unittest.main()
