from __future__ import annotations

import json
import os
from typing import Any


class SecretsConfigError(RuntimeError):
    """Raised when secrets-backed configuration cannot be loaded."""


def resolve_environment(
    raw_env: dict[str, str] | None = None,
    *,
    ssm_client: Any | None = None,
    secrets_client: Any | None = None,
) -> dict[str, str]:
    """
    Resolve runtime environment with optional AWS config-store overlays.

    Preferred source: `AWS_SSM_PARAMETER_NAMES` (comma-separated names of SSM
    SecureString parameters). Each parameter value must be a JSON object.

    Legacy source: `AWS_SECRETS_MANAGER_SECRET_IDS` (comma-separated IDs/ARNs
    of Secrets Manager JSON secrets).

    Merge precedence:
      1) Secrets Manager (legacy)
      2) SSM Parameter Store (preferred)
      3) Explicit process env vars (highest)
    """
    base_env = dict(os.environ if raw_env is None else raw_env)
    region_name = base_env.get("AWS_REGION")
    secret_ids = _parse_csv(base_env.get("AWS_SECRETS_MANAGER_SECRET_IDS"))
    parameter_names = _parse_csv(base_env.get("AWS_SSM_PARAMETER_NAMES"))
    if not secret_ids and not parameter_names:
        return base_env

    resolved: dict[str, str] = {}
    if secret_ids:
        secret_client = secrets_client or _default_secrets_client(
            region_name=region_name
        )
        for secret_id in secret_ids:
            payload = _load_secret_payload(client=secret_client, secret_id=secret_id)
            _merge_payload(target=resolved, payload=payload)

    if parameter_names:
        parameter_client = ssm_client or _default_ssm_client(region_name=region_name)
        for parameter_name in parameter_names:
            payload = _load_parameter_payload(
                client=parameter_client,
                parameter_name=parameter_name,
            )
            _merge_payload(target=resolved, payload=payload)

    # Environment variables override secret values to keep local/manual overrides easy.
    resolved.update(base_env)
    return resolved


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _merge_payload(*, target: dict[str, str], payload: dict[str, Any]) -> None:
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            target[key] = json.dumps(value, separators=(",", ":"))
        else:
            target[key] = str(value)


def _default_ssm_client(*, region_name: str | None) -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise SecretsConfigError(
            "boto3 is required for SSM Parameter Store loading"
        ) from exc
    kwargs: dict[str, Any] = {}
    if region_name:
        kwargs["region_name"] = region_name
    return boto3.client("ssm", **kwargs)


def _default_secrets_client(*, region_name: str | None) -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise SecretsConfigError(
            "boto3 is required for Secrets Manager loading"
        ) from exc
    kwargs: dict[str, Any] = {}
    if region_name:
        kwargs["region_name"] = region_name
    return boto3.client("secretsmanager", **kwargs)


def _load_secret_payload(*, client: Any, secret_id: str) -> dict[str, Any]:
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:
        raise SecretsConfigError(f"Failed to load secret {secret_id}: {exc}") from exc

    secret_string = response.get("SecretString")
    if not secret_string:
        raise SecretsConfigError(
            f"Secret {secret_id} does not have SecretString; binary secrets are unsupported"
        )
    try:
        payload = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise SecretsConfigError(
            f"Secret {secret_id} must contain a JSON object; parse failed: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SecretsConfigError(f"Secret {secret_id} must contain a JSON object")
    return payload


def _load_parameter_payload(*, client: Any, parameter_name: str) -> dict[str, Any]:
    try:
        response = client.get_parameter(Name=parameter_name, WithDecryption=True)
    except Exception as exc:
        raise SecretsConfigError(
            f"Failed to load parameter {parameter_name}: {exc}"
        ) from exc

    parameter = response.get("Parameter", {})
    value = parameter.get("Value")
    if not value:
        raise SecretsConfigError(f"Parameter {parameter_name} does not have a value")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SecretsConfigError(
            f"Parameter {parameter_name} must contain a JSON object; parse failed: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SecretsConfigError(
            f"Parameter {parameter_name} must contain a JSON object"
        )
    return payload
