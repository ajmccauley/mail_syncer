from __future__ import annotations

import json

from src.config import load_config


def test_load_config_from_sync_routes_json_multi_route() -> None:
    env = {
        "AWS_REGION": "us-east-1",
        "DYNAMODB_TABLE": "mail-syncer-state",
        "OUTLOOK_EMAIL": "outlook@example.com",
        "MS_CLIENT_ID": "ms-client",
        "MS_REFRESH_TOKEN": "ms-refresh",
        "SYNC_ROUTES_JSON": json.dumps(
            [
                {
                    "gmail_email": "g1@example.com",
                    "gmail_client_id": "g1-client",
                    "gmail_client_secret": "g1-secret",
                    "gmail_refresh_token": "g1-refresh",
                    "outlook_target_folder": "Inbox/Gmail-1",
                },
                {
                    "gmail_email": "g2@example.com",
                    "gmail_client_id": "g2-client",
                    "gmail_client_secret": "g2-secret",
                    "gmail_refresh_token": "g2-refresh",
                    "outlook_target_folder": "Inbox/Gmail-2",
                },
            ]
        ),
    }
    config = load_config(env)
    assert config.route_count == 2
    assert config.routes[0].outlook_email == "outlook@example.com"
    assert config.routes[1].gmail_email == "g2@example.com"
    assert config.uidvalidity_resync_hours == 24
    assert config.imap_max_retries == 3


def test_load_config_single_route_fallback_mode() -> None:
    env = {
        "AWS_REGION": "us-east-1",
        "DYNAMODB_TABLE": "mail-syncer-state",
        "OUTLOOK_EMAIL": "outlook@example.com",
        "MS_CLIENT_ID": "ms-client",
        "MS_REFRESH_TOKEN": "ms-refresh",
        "GMAIL_EMAIL": "g1@example.com",
        "GMAIL_CLIENT_ID": "g-client",
        "GMAIL_CLIENT_SECRET": "g-secret",
        "GMAIL_REFRESH_TOKEN": "g-refresh",
        "OUTLOOK_TARGET_FOLDER": "Inbox/Gmail-1",
    }
    config = load_config(env)
    assert config.route_count == 1
    assert config.routes[0].gmail_email == "g1@example.com"
    assert config.gmail_imap_host == "imap.gmail.com"
    assert config.outlook_imap_host == "outlook.office365.com"
