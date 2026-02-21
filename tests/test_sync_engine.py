from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from src.config import AppConfig, RouteConfig
from src.dynamodb_state import Watermark
from src.imap_utils import rfc822_sha256
from src.sync_engine import SyncEngine


@dataclass(frozen=True, slots=True)
class FakeToken:
    access_token: str


class FakeStateStore:
    def __init__(self, *, watermark: Watermark, duplicate_hashes: set[str] | None = None) -> None:
        self._watermark = watermark
        self.duplicate_hashes = duplicate_hashes or set()
        self.finalized: list[tuple[int, int]] = []
        self.failures: list[tuple[int, int, str]] = []
        self.abandoned: list[tuple[int, int]] = []
        self.claimed: list[tuple[int, int]] = []
        self.set_watermark_calls: list[tuple[int, int]] = []

    def assert_available(self) -> None:
        return None

    def route_pk(self, *, gmail_email: str, outlook_email: str, folder: str) -> str:
        return f"ROUTE#{gmail_email}#{outlook_email}#{folder}"

    def get_watermark(self, *, pk: str) -> Watermark:
        return self._watermark

    def set_watermark(self, *, pk: str, uidvalidity: int, last_uid: int) -> None:
        self.set_watermark_calls.append((uidvalidity, last_uid))
        self._watermark = Watermark(uidvalidity=uidvalidity, last_uid=last_uid)

    def payload_already_copied(
        self, *, pk: str, message_id_header: str | None, rfc822_sha256: str
    ) -> bool:
        return rfc822_sha256 in self.duplicate_hashes

    def uid_record_exists(self, *, pk: str, uidvalidity: int, gmail_uid: int) -> bool:
        return False

    def claim_uid_copy(self, *, pk: str, uidvalidity: int, gmail_uid: int) -> bool:
        self.claimed.append((uidvalidity, gmail_uid))
        return True

    def finalize_uid_copy(
        self,
        *,
        pk: str,
        uidvalidity: int,
        gmail_uid: int,
        message_id_header: str | None,
        rfc822_sha256: str,
        ttl_days: int,
    ) -> None:
        self.finalized.append((uidvalidity, gmail_uid))

    def abandon_pending_uid(self, *, pk: str, uidvalidity: int, gmail_uid: int) -> None:
        self.abandoned.append((uidvalidity, gmail_uid))

    def record_failure(
        self,
        *,
        pk: str,
        uidvalidity: int,
        gmail_uid: int,
        error_message: str,
        ttl_days: int,
    ) -> None:
        self.failures.append((uidvalidity, gmail_uid, error_message))


class FakeGmailClient:
    def __init__(
        self,
        *,
        uidvalidity: int,
        uids_after: list[int],
        uids_since: list[int],
        messages: dict[int, bytes],
    ) -> None:
        self._uidvalidity = uidvalidity
        self._uids_after = uids_after
        self._uids_since = uids_since
        self._messages = messages
        self.search_after_calls = 0
        self.search_since_calls = 0

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_uidvalidity(self) -> int:
        return self._uidvalidity

    def search_uids_after(self, *, last_uid: int) -> list[int]:
        self.search_after_calls += 1
        return list(self._uids_after)

    def search_uids_since(self, *, since_date: date) -> list[int]:
        self.search_since_calls += 1
        return list(self._uids_since)

    def fetch_rfc822(self, *, uid: int) -> bytes:
        return self._messages[uid]


class FakeOutlookClient:
    def __init__(self, *, fail_marker: bytes | None = None) -> None:
        self.fail_marker = fail_marker
        self.appended: list[bytes] = []

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def ensure_folder(self, folder_name: str, *, create_if_missing: bool) -> None:
        return None

    def append_rfc822(self, *, folder_name: str, raw_rfc822: bytes) -> None:
        if self.fail_marker and self.fail_marker in raw_rfc822:
            raise RuntimeError("append failed")
        self.appended.append(raw_rfc822)


def _base_config() -> AppConfig:
    route = RouteConfig(
        gmail_email="g1@example.com",
        gmail_client_id="gid",
        gmail_client_secret="gsecret",
        gmail_refresh_token="grefresh",
        outlook_email="outlook@example.com",
        outlook_target_folder="Inbox/Gmail-1",
    )
    return AppConfig(
        aws_region="us-east-1",
        dynamodb_table="state-table",
        outlook_email="outlook@example.com",
        ms_client_id="msid",
        ms_client_secret=None,
        ms_tenant="consumers",
        ms_refresh_token="msrefresh",
        sync_interval_seconds=300,
        uidvalidity_resync_hours=24,
        uid_record_ttl_days=365,
        fail_record_ttl_days=14,
        imap_timeout_seconds=30,
        imap_max_retries=1,
        imap_retry_base_seconds=0.01,
        gmail_imap_host="imap.gmail.com",
        gmail_imap_port=993,
        outlook_imap_host="outlook.office365.com",
        outlook_imap_port=993,
        log_level="INFO",
        routes=(route,),
    )


def _gmail_message(uid: int, message_id: str) -> bytes:
    return (
        f"From: sender@example.com\r\n"
        f"To: receiver@example.com\r\n"
        f"Message-ID: <{message_id}@example.com>\r\n"
        f"Subject: UID-{uid}\r\n"
        "\r\n"
        f"body-{uid}"
    ).encode("utf-8")


def test_uidvalidity_change_uses_since_search_and_fingerprint_dedupe() -> None:
    config = _base_config()
    duplicate_raw = _gmail_message(60, "dup")
    unique_raw = _gmail_message(61, "new")
    duplicate_hash = rfc822_sha256(duplicate_raw)
    state = FakeStateStore(
        watermark=Watermark(uidvalidity=100, last_uid=50),
        duplicate_hashes={duplicate_hash},
    )
    gmail = FakeGmailClient(
        uidvalidity=200,
        uids_after=[],
        uids_since=[60, 61],
        messages={60: duplicate_raw, 61: unique_raw},
    )
    outlook = FakeOutlookClient()
    engine = SyncEngine(
        config=config,
        state_store=state,  # type: ignore[arg-type]
        logger=logging.getLogger("test"),
        gmail_refresh_fn=lambda **_: FakeToken(access_token="gmail-token"),
        ms_refresh_fn=lambda **_: FakeToken(access_token="ms-token"),
        gmail_client_factory=lambda **_: gmail,  # type: ignore[arg-type]
        outlook_client_factory=lambda **_: outlook,  # type: ignore[arg-type]
        sleep_fn=lambda _: None,
    )

    result = engine.run_once(dry_run=False)
    route_result = result.route_results[0]

    assert route_result.copied == 1
    assert route_result.skipped_duplicates == 1
    assert route_result.failed == 0
    assert gmail.search_since_calls == 1
    assert gmail.search_after_calls == 0
    assert state.finalized == [(200, 61)]
    assert state.set_watermark_calls[-1] == (200, 61)


def test_route_continues_on_append_failure_and_keeps_replay_window() -> None:
    config = _base_config()
    messages = {
        101: _gmail_message(101, "a"),
        102: _gmail_message(102, "b"),
        103: _gmail_message(103, "c"),
    }
    state = FakeStateStore(watermark=Watermark(uidvalidity=300, last_uid=100))
    gmail = FakeGmailClient(
        uidvalidity=300,
        uids_after=[101, 102, 103],
        uids_since=[],
        messages=messages,
    )
    outlook = FakeOutlookClient(fail_marker=b"UID-102")
    engine = SyncEngine(
        config=config,
        state_store=state,  # type: ignore[arg-type]
        logger=logging.getLogger("test"),
        gmail_refresh_fn=lambda **_: FakeToken(access_token="gmail-token"),
        ms_refresh_fn=lambda **_: FakeToken(access_token="ms-token"),
        gmail_client_factory=lambda **_: gmail,  # type: ignore[arg-type]
        outlook_client_factory=lambda **_: outlook,  # type: ignore[arg-type]
        sleep_fn=lambda _: None,
    )

    result = engine.run_once(dry_run=False)
    route_result = result.route_results[0]

    assert route_result.status == "partial_failure"
    assert route_result.copied == 2
    assert route_result.failed == 1
    assert state.finalized == [(300, 101), (300, 103)]
    assert state.abandoned == [(300, 102)]
    assert state.failures and state.failures[0][1] == 102
    assert state.set_watermark_calls[-1] == (300, 101)

