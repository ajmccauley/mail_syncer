from __future__ import annotations

import json
from typing import Any

import pytest

from src.secrets_config import SecretsConfigError, resolve_environment


class FakeSecretsClient:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads

    def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
        if SecretId not in self.payloads:
            raise RuntimeError("missing secret")
        return {"SecretString": json.dumps(self.payloads[SecretId])}


def test_resolve_environment_merges_multiple_secrets_and_preserves_env_override() -> None:
    env = {
        "AWS_REGION": "us-east-1",
        "AWS_SECRETS_MANAGER_SECRET_IDS": "s1, s2",
        "LOG_LEVEL": "DEBUG",
    }
    client = FakeSecretsClient(
        payloads={
            "s1": {"LOG_LEVEL": "INFO", "MS_CLIENT_ID": "from-secret"},
            "s2": {"SYNC_ROUTES_JSON": [{"gmail_email": "g@example.com"}]},
        }
    )
    resolved = resolve_environment(env, secrets_client=client)
    assert resolved["LOG_LEVEL"] == "DEBUG"
    assert resolved["MS_CLIENT_ID"] == "from-secret"
    assert resolved["SYNC_ROUTES_JSON"].startswith("[")


def test_resolve_environment_raises_for_invalid_secret_payload() -> None:
    class BadSecretsClient:
        def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
            return {"SecretString": "not-json"}

    with pytest.raises(SecretsConfigError):
        resolve_environment(
            {
                "AWS_REGION": "us-east-1",
                "AWS_SECRETS_MANAGER_SECRET_IDS": "bad",
            },
            secrets_client=BadSecretsClient(),
        )

