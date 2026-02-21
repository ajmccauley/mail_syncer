from __future__ import annotations

from src.imap_utils import extract_message_id, rfc822_sha256


def test_extract_message_id() -> None:
    raw = (
        b"From: sender@example.com\r\n"
        b"To: receiver@example.com\r\n"
        b"Message-ID: <abc123@example.com>\r\n"
        b"Subject: Test\r\n"
        b"\r\n"
        b"hello"
    )
    assert extract_message_id(raw) == "<abc123@example.com>"


def test_rfc822_sha256_is_stable() -> None:
    raw = b"Subject: Test\r\n\r\nBody"
    first = rfc822_sha256(raw)
    second = rfc822_sha256(raw)
    assert first == second
    assert len(first) == 64

