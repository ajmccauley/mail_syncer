from __future__ import annotations

import imaplib
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from src.imap_utils import build_xoauth2_string


GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993


class GmailImapError(RuntimeError):
    """Raised for Gmail IMAP authentication and command failures."""


@dataclass(frozen=True, slots=True)
class GmailMessage:
    uid: int
    raw_rfc822: bytes


class GmailImapClient:
    def __init__(
        self,
        *,
        email_address: str,
        access_token: str,
        host: str = GMAIL_IMAP_HOST,
        port: int = GMAIL_IMAP_PORT,
        timeout_seconds: int = 30,
        imap_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.email_address = email_address
        self.access_token = access_token
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self._imap_factory = imap_factory or imaplib.IMAP4_SSL
        self._imap: Any | None = None

    def connect(self) -> None:
        if self._imap is not None:
            return
        try:
            self._imap = self._imap_factory(
                self.host, self.port, timeout=self.timeout_seconds
            )
            xoauth2 = build_xoauth2_string(self.email_address, self.access_token)
            result, _ = self._imap.authenticate(
                "XOAUTH2", lambda _: xoauth2.encode("utf-8")
            )
            if result != "OK":
                raise GmailImapError("Gmail XOAUTH2 authentication failed")
        except Exception as exc:
            raise GmailImapError(f"Gmail IMAP connection/auth failed: {exc}") from exc

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except Exception:
            pass
        self._imap = None

    def get_uidvalidity(self) -> int:
        self._select_inbox()
        response = self._imap.response("UIDVALIDITY")
        uidvalidity_raw = None
        if isinstance(response, tuple) and len(response) > 1:
            payload = response[1]
            if isinstance(payload, (list, tuple)) and payload:
                uidvalidity_raw = payload[-1]
        if isinstance(uidvalidity_raw, bytes):
            uidvalidity_raw = uidvalidity_raw.decode("ascii", errors="ignore")
        try:
            return int(uidvalidity_raw)
        except (TypeError, ValueError) as exc:
            raise GmailImapError(
                f"Unable to parse UIDVALIDITY from Gmail response: {response}"
            ) from exc

    def search_uids_after(self, *, last_uid: int) -> list[int]:
        self._select_inbox()
        start_uid = max(last_uid + 1, 1)
        typ, data = self._imap.uid("SEARCH", None, f"UID {start_uid}:*")
        if typ != "OK":
            raise GmailImapError(f"Gmail UID SEARCH failed: {typ} {data}")
        return _parse_uid_list(data)

    def search_uids_since(self, *, since_date: date) -> list[int]:
        self._select_inbox()
        date_str = since_date.strftime("%d-%b-%Y")
        typ, data = self._imap.uid("SEARCH", None, "SINCE", date_str)
        if typ != "OK":
            raise GmailImapError(f"Gmail UID SEARCH SINCE failed: {typ} {data}")
        return _parse_uid_list(data)

    def fetch_rfc822(self, *, uid: int) -> bytes:
        self._select_inbox()
        typ, data = self._imap.uid("FETCH", str(uid), "(RFC822)")
        if typ != "OK":
            raise GmailImapError(f"Gmail UID FETCH failed for {uid}: {typ} {data}")
        for part in data:
            if (
                isinstance(part, tuple)
                and len(part) > 1
                and isinstance(part[1], (bytes, bytearray))
            ):
                return bytes(part[1])
        raise GmailImapError(f"Gmail UID FETCH returned no RFC822 payload for {uid}")

    def _select_inbox(self) -> None:
        if self._imap is None:
            raise GmailImapError("Gmail IMAP client is not connected")
        typ, data = self._imap.select("INBOX", readonly=True)
        if typ != "OK":
            raise GmailImapError(f"Gmail INBOX SELECT failed: {typ} {data}")


def _parse_uid_list(data: Any) -> list[int]:
    if not data:
        return []
    joined: list[str] = []
    for part in data:
        if isinstance(part, bytes):
            joined.append(part.decode("ascii", errors="ignore"))
        elif isinstance(part, str):
            joined.append(part)
    if not joined:
        return []
    raw = " ".join(joined).strip()
    if not raw:
        return []
    uids: list[int] = []
    for token in raw.split():
        try:
            uids.append(int(token))
        except ValueError:
            continue
    return sorted(set(uids))
