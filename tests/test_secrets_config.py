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


class FakeSsmClient:
    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads

    def get_parameter(self, *, Name: str, WithDecryption: bool) -> dict[str, Any]:
        assert WithDecryption is True
        if Name not in self.payloads:
            raise RuntimeError("missing parameter")
        return {"Parameter": {"Value": json.dumps(self.payloads[Name])}}


def test_resolve_environment_merges_ssm_parameters_and_preserves_env_override() -> None:
    env = {
        "AWS_REGION": "us-east-1",
        "AWS_SSM_PARAMETER_NAMES": "/mail-syncer/p1,/mail-syncer/p2",
        "LOG_LEVEL": "DEBUG",
    }
    client = FakeSsmClient(
        payloads={
            "/mail-syncer/p1": {"LOG_LEVEL": "INFO", "MS_CLIENT_ID": "from-ssm"},
            "/mail-syncer/p2": {"SYNC_ROUTES_JSON": [{"gmail_email": "g@example.com"}]},
        }
    )
    resolved = resolve_environment(env, ssm_client=client)
    assert resolved["LOG_LEVEL"] == "DEBUG"
    assert resolved["MS_CLIENT_ID"] == "from-ssm"
    assert resolved["SYNC_ROUTES_JSON"].startswith("[")


def test_resolve_environment_uses_ssm_values_over_legacy_secrets() -> None:
    env = {
        "AWS_REGION": "us-east-1",
        "AWS_SECRETS_MANAGER_SECRET_IDS": "legacy",
        "AWS_SSM_PARAMETER_NAMES": "/preferred",
    }
    secrets_client = FakeSecretsClient(
        payloads={"legacy": {"MS_CLIENT_ID": "legacy-client"}}
    )
    ssm_client = FakeSsmClient(payloads={"/preferred": {"MS_CLIENT_ID": "ssm-client"}})
    resolved = resolve_environment(
        env, secrets_client=secrets_client, ssm_client=ssm_client
    )
    assert resolved["MS_CLIENT_ID"] == "ssm-client"


def test_resolve_environment_raises_for_invalid_ssm_payload() -> None:
    class BadSsmClient:
        def get_parameter(self, *, Name: str, WithDecryption: bool) -> dict[str, Any]:
            return {"Parameter": {"Value": "not-json"}}

    with pytest.raises(SecretsConfigError):
        resolve_environment(
            {
                "AWS_REGION": "us-east-1",
                "AWS_SSM_PARAMETER_NAMES": "/bad",
            },
            ssm_client=BadSsmClient(),
        )


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
