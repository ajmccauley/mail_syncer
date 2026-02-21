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
        uidvalidity_resync_hours=24,
        uid_record_ttl_days=365,
        fail_record_ttl_days=14,
        imap_timeout_seconds=30,
        imap_max_retries=3,
        imap_retry_base_seconds=0.1,
        gmail_imap_host="imap.gmail.com",
        gmail_imap_port=993,
        outlook_imap_host="outlook.office365.com",
        outlook_imap_port=993,
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
