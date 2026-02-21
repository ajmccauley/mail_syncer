from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass


class OAuthError(RuntimeError):
    """Raised when OAuth token exchanges fail."""


@dataclass(frozen=True, slots=True)
class OAuthToken:
    access_token: str
    token_type: str
    expires_at_epoch: int


def refresh_access_token(
    *,
    tenant: str,
    client_id: str,
    client_secret: str | None,
    refresh_token: str,
    timeout_seconds: int = 10,
) -> OAuthToken:
    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
    }
    if client_secret:
        payload["client_secret"] = client_secret
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        token_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - network path
        raise OAuthError(f"Microsoft token refresh request failed: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OAuthError("Microsoft token endpoint returned invalid JSON") from exc

    access_token = data.get("access_token")
    token_type = data.get("token_type", "Bearer")
    expires_in = data.get("expires_in", 3600)
    if not access_token:
        raise OAuthError(f"Microsoft token refresh failed: {data}")
    return OAuthToken(
        access_token=str(access_token),
        token_type=str(token_type),
        expires_at_epoch=int(time.time()) + int(expires_in),
    )


def interactive_token_helper() -> None:
    raise NotImplementedError(
        "Interactive Microsoft OAuth helper is not implemented yet. "
        "Use pre-generated refresh tokens for now."
    )

