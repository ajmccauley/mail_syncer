from __future__ import annotations


OUTLOOK_IMAP_HOST = "outlook.office365.com"
OUTLOOK_IMAP_PORT = 993


class OutlookImapClient:
    """
    Outlook IMAP client placeholder.

    APPEND and folder management implementation is intentionally deferred while
    first-batch foundation tasks are completed (config/state/runtime safety gate).
    """

    def __init__(self, email_address: str) -> None:
        self.email_address = email_address

    def ensure_folder(self, folder_name: str, *, create_if_missing: bool) -> None:
        raise NotImplementedError("Outlook folder ensure/create not implemented yet")

    def append_rfc822(self, folder_name: str, raw_rfc822: bytes) -> None:
        raise NotImplementedError("Outlook APPEND not implemented yet")

