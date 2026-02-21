from __future__ import annotations

import imaplib
from typing import Any, Callable

from src.imap_utils import build_xoauth2_string


OUTLOOK_IMAP_HOST = "outlook.office365.com"
OUTLOOK_IMAP_PORT = 993


class OutlookImapError(RuntimeError):
    """Raised for Outlook IMAP authentication and command failures."""


class OutlookImapClient:
    def __init__(
        self,
        *,
        email_address: str,
        access_token: str,
        host: str = OUTLOOK_IMAP_HOST,
        port: int = OUTLOOK_IMAP_PORT,
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
            result, _ = self._imap.authenticate("XOAUTH2", lambda _: xoauth2.encode("utf-8"))
            if result != "OK":
                raise OutlookImapError("Outlook XOAUTH2 authentication failed")
        except Exception as exc:
            raise OutlookImapError(f"Outlook IMAP connection/auth failed: {exc}") from exc

    def close(self) -> None:
        if self._imap is None:
            return
        try:
            self._imap.logout()
        except Exception:
            pass
        self._imap = None

    def ensure_folder(self, folder_name: str, *, create_if_missing: bool) -> None:
        if self._imap is None:
            raise OutlookImapError("Outlook IMAP client is not connected")
        typ, _ = self._imap.select(folder_name, readonly=True)
        if typ == "OK":
            return
        if not create_if_missing:
            raise OutlookImapError(f"Outlook folder does not exist: {folder_name}")
        create_typ, create_data = self._imap.create(folder_name)
        if create_typ != "OK":
            raise OutlookImapError(
                f"Outlook folder create failed for {folder_name}: {create_typ} {create_data}"
            )

    def append_rfc822(self, *, folder_name: str, raw_rfc822: bytes) -> None:
        if self._imap is None:
            raise OutlookImapError("Outlook IMAP client is not connected")
        # No \Seen flag by default so destination message remains unread.
        typ, data = self._imap.append(folder_name, None, None, raw_rfc822)
        if typ != "OK":
            raise OutlookImapError(f"Outlook APPEND failed: {typ} {data}")

