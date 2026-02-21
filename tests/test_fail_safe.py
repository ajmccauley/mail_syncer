from __future__ import annotations

import logging

import pytest

from src.config import AppConfig, RouteConfig
from src.dynamodb_state import DynamoStateStore, DynamoUnavailableError
from src.sync_engine import SyncEngine


class BrokenDynamoClient:
    def describe_table(self, **_: object) -> dict[str, object]:
        raise RuntimeError("simulated dynamodb outage")


def _test_config() -> AppConfig:
    route = RouteConfig(
        gmail_email="g1@example.com",
        gmail_client_id="cid",
        gmail_client_secret="secret",
        gmail_refresh_token="refresh",
        outlook_email="outlook@example.com",
        outlook_target_folder="Inbox/Gmail-1",
    )
    return AppConfig(
        aws_region="us-east-1",
        dynamodb_table="table",
        outlook_email="outlook@example.com",
        ms_client_id="ms-client",
        ms_client_secret=None,
        ms_tenant="consumers",
        ms_refresh_token="ms-refresh",
        sync_interval_seconds=300,
        log_level="INFO",
        routes=(route,),
    )


def test_run_once_aborts_when_dynamodb_unavailable() -> None:
    store = DynamoStateStore(
        table_name="table",
        region_name="us-east-1",
        client=BrokenDynamoClient(),
    )
    engine = SyncEngine(
        config=_test_config(),
        state_store=store,
        logger=logging.getLogger("test"),
    )
    with pytest.raises(DynamoUnavailableError):
        engine.run_once(dry_run=True)

