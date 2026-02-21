from __future__ import annotations

import base64
import hashlib
from email import policy
from email.parser import BytesParser


def build_xoauth2_string(email_address: str, access_token: str) -> str:
    # SASL XOAUTH2 format uses \x01 control characters as separators.
    return f"user={email_address}\x01auth=Bearer {access_token}\x01\x01"


def build_xoauth2_b64(email_address: str, access_token: str) -> str:
    raw = build_xoauth2_string(email_address, access_token).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def rfc822_sha256(raw_message: bytes) -> str:
    return hashlib.sha256(raw_message).hexdigest()


def extract_message_id(raw_message: bytes) -> str | None:
    parsed = BytesParser(policy=policy.default).parsebytes(raw_message)
    message_id = parsed.get("Message-ID")
    if not message_id:
        return None
    return message_id.strip()
