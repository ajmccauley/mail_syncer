#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Mapping:
    secret_id: str
    parameter_name: str


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy JSON secrets from AWS Secrets Manager into "
            "AWS SSM Parameter Store SecureString parameters."
        )
    )
    parser.add_argument(
        "--mapping",
        action="append",
        required=True,
        help=(
            "Mapping entry in format <secret-id>=<parameter-name>. "
            "Repeat for multiple entries."
        ),
    )
    parser.add_argument("--region", default=None)
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing SSM parameters if they already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned writes only; do not write SSM parameters.",
    )
    return parser.parse_args(argv)


def _parse_mapping(raw: str) -> Mapping:
    if "=" not in raw:
        raise ValueError(
            f"Invalid mapping '{raw}'. Expected format <secret-id>=<parameter-name>."
        )
    secret_id, parameter_name = raw.split("=", 1)
    secret_id = secret_id.strip()
    parameter_name = parameter_name.strip()
    if not secret_id or not parameter_name:
        raise ValueError(
            f"Invalid mapping '{raw}'. Secret ID and parameter name are required."
        )
    return Mapping(secret_id=secret_id, parameter_name=parameter_name)


def _load_secret_json(*, secrets_client: Any, secret_id: str) -> dict[str, Any]:
    response = secrets_client.get_secret_value(SecretId=secret_id)
    secret_string = response.get("SecretString")
    if not secret_string:
        raise RuntimeError(
            f"Secret {secret_id} has no SecretString; binary secrets are unsupported."
        )
    try:
        payload = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Secret {secret_id} contains invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Secret {secret_id} must contain a JSON object.")
    return payload


def _put_parameter(
    *,
    ssm_client: Any,
    parameter_name: str,
    payload: dict[str, Any],
    overwrite: bool,
) -> None:
    ssm_client.put_parameter(
        Name=parameter_name,
        Type="SecureString",
        Value=json.dumps(payload, separators=(",", ":")),
        Overwrite=overwrite,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        import boto3
    except ImportError as exc:
        print("boto3 is required to run this script.", file=sys.stderr)
        raise SystemExit(3) from exc

    kwargs: dict[str, Any] = {}
    if args.region:
        kwargs["region_name"] = args.region
    secrets_client = boto3.client("secretsmanager", **kwargs)
    ssm_client = boto3.client("ssm", **kwargs)

    mappings: list[Mapping] = []
    try:
        mappings = [_parse_mapping(raw) for raw in args.mapping]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for mapping in mappings:
        try:
            payload = _load_secret_json(
                secrets_client=secrets_client,
                secret_id=mapping.secret_id,
            )
            if not args.dry_run:
                _put_parameter(
                    ssm_client=ssm_client,
                    parameter_name=mapping.parameter_name,
                    payload=payload,
                    overwrite=args.overwrite,
                )
            results.append(
                {
                    "secret_id": mapping.secret_id,
                    "parameter_name": mapping.parameter_name,
                    "status": "dry_run" if args.dry_run else "written",
                    "key_count": len(payload),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "secret_id": mapping.secret_id,
                    "parameter_name": mapping.parameter_name,
                    "status": "error",
                    "error": str(exc),
                }
            )

    print(json.dumps({"results": results}, indent=2))
    has_error = any(result["status"] == "error" for result in results)
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
