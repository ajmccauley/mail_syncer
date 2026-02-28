from __future__ import annotations

import argparse

import pytest

from src.main import _resolve_token_store


def _args(**overrides: str | None) -> argparse.Namespace:
    base: dict[str, str | None] = {
        "write_parameter_name": None,
        "write_parameter_key": "GMAIL_REFRESH_TOKEN",
        "write_secret_id": None,
        "write_secret_key": "GMAIL_REFRESH_TOKEN",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_resolve_token_store_prefers_parameter_target() -> None:
    args = _args(write_parameter_name="/mail-syncer/routes")
    assert _resolve_token_store(args, default_key="GMAIL_REFRESH_TOKEN") == (
        "parameter",
        "/mail-syncer/routes",
        "GMAIL_REFRESH_TOKEN",
    )


def test_resolve_token_store_uses_secret_target_when_requested() -> None:
    args = _args(write_secret_id="mail-syncer/routes")
    assert _resolve_token_store(args, default_key="GMAIL_REFRESH_TOKEN") == (
        "secret",
        "mail-syncer/routes",
        "GMAIL_REFRESH_TOKEN",
    )


def test_resolve_token_store_rejects_multiple_targets() -> None:
    args = _args(
        write_parameter_name="/mail-syncer/routes",
        write_secret_id="mail-syncer/routes",
    )
    with pytest.raises(ValueError):
        _resolve_token_store(args, default_key="GMAIL_REFRESH_TOKEN")
