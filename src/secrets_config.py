from __future__ import annotations

import json
import os
from typing import Any


class SecretsConfigError(RuntimeError):
    """Raised when secrets-backed configuration cannot be loaded."""


def resolve_environment(
    raw_env: dict[str, str] | None = None,
    *,
    secrets_client: Any | None = None,
) -> dict[str, str]:
    """
    Resolve runtime environment with optional AWS Secrets Manager overlays.

    `AWS_SECRETS_MANAGER_SECRET_IDS` can contain a comma-separated list of
    secret IDs/ARNs. Each secret must be a JSON object; keys are merged into
    environment values. Explicit environment variables take precedence.
    """
    base_env = dict(os.environ if raw_env is None else raw_env)
    secret_ids_raw = base_env.get("AWS_SECRETS_MANAGER_SECRET_IDS", "").strip()
    if not secret_ids_raw:
        return base_env

    secret_ids = [part.strip() for part in secret_ids_raw.split(",") if part.strip()]
    if not secret_ids:
        return base_env

    resolved: dict[str, str] = {}
    client = secrets_client or _default_secrets_client(
        region_name=base_env.get("AWS_REGION")
    )
    for secret_id in secret_ids:
        payload = _load_secret_payload(client=client, secret_id=secret_id)
        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            if value is None:
                continue
            if isinstance(value, (dict, list)):
                resolved[key] = json.dumps(value, separators=(",", ":"))
            else:
                resolved[key] = str(value)

    # Environment variables override secret values to keep local/manual overrides easy.
    resolved.update(base_env)
    return resolved


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
