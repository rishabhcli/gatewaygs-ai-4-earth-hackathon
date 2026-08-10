#!/usr/bin/env python3
"""Semantic readiness probes for repository-owned stateful boundaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import psycopg
from minio.error import S3Error
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from scripts.init_object_store import BUCKET, client
from services.runtime.config import DatabaseTarget

REPOSITORY_NAME = "gatewaygs-ai-4-earth-hackathon"
CATALOG_READINESS_FIELD_COUNT = 2


def _root() -> Path:
    root = Path(__file__).resolve().parents[1]
    if root.name != REPOSITORY_NAME:
        raise RuntimeError("repository identity check failed")
    return root


def probe_postgis(root: Path) -> dict[str, str]:
    target = DatabaseTarget()
    with (
        psycopg.connect(
            target.dsn(root).get_secret_value(), connect_timeout=2
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_setting('server_version'), postgis_version()")
        row = cursor.fetchone()
    if (
        row is None
        or len(row) != CATALOG_READINESS_FIELD_COUNT
        or not all(isinstance(value, str) and value for value in row)
    ):
        raise RuntimeError("catalog readiness query returned an invalid result")
    return {
        "contract_version": "1",
        "service": "postgis",
        "status": "ready",
        "postgres_version": row[0],
        "postgis_version": row[1],
    }


def probe_minio(root: Path) -> dict[str, str]:
    if not client(root).bucket_exists(BUCKET):
        raise RuntimeError("repository object bucket does not exist")
    return {
        "contract_version": "1",
        "service": "minio",
        "status": "ready",
        "bucket": BUCKET,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=("postgis", "minio"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        payload = (
            probe_postgis(_root())
            if args.service == "postgis"
            else probe_minio(_root())
        )
    except OSError, RuntimeError, S3Error, Urllib3HTTPError, psycopg.Error:
        print(  # noqa: T201 - command-json protocol writes one bounded JSON object
            json.dumps(
                {
                    "contract_version": "1",
                    "service": args.service,
                    "status": "not-ready",
                    "code": f"{args.service.upper()}_UNAVAILABLE",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 1
    print(  # noqa: T201 - command-json protocol writes one bounded JSON object
        json.dumps(payload, separators=(",", ":"), sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
