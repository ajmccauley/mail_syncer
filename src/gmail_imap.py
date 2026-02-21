from __future__ import annotations

from dataclasses import dataclass


GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993


@dataclass(frozen=True, slots=True)
class GmailMessage:
    uid: int
    raw_rfc822: bytes


class GmailImapClient:
    """
    Gmail IMAP client placeholder.

    Real message fetch implementation is intentionally deferred while first-batch
    foundation tasks are completed (config/state/runtime safety gate).
    """

    def __init__(self, email_address: str) -> None:
        self.email_address = email_address

    def fetch_new_messages(self, last_uid: int | None) -> list[GmailMessage]:
        raise NotImplementedError("Gmail IMAP incremental fetch not implemented yet")

