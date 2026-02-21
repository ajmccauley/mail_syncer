from __future__ import annotations

import json
import secrets
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event


MS_DEFAULT_SCOPE = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"


class OAuthError(RuntimeError):
    """Raised when OAuth token exchanges fail."""


@dataclass(frozen=True, slots=True)
class OAuthToken:
    access_token: str
    token_type: str
    expires_at_epoch: int


@dataclass(frozen=True, slots=True)
class OAuthInteractiveResult:
    refresh_token: str
    access_token: str
    expires_at_epoch: int
    scope: str
    raw_response: dict[str, object]


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
        "scope": MS_DEFAULT_SCOPE,
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


def interactive_token_helper(
    *,
    tenant: str,
    client_id: str,
    client_secret: str | None,
    scope: str = MS_DEFAULT_SCOPE,
    listen_host: str = "localhost",
    listen_port: int = 8766,
    timeout_seconds: int = 180,
    open_browser: bool = True,
) -> OAuthInteractiveResult:
    state = secrets.token_urlsafe(24)
    redirect_uri = f"http://{listen_host}:{listen_port}/callback"
    auth_url = _build_auth_url(
        tenant=tenant,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        state=state,
    )
    received = _wait_for_auth_code(
        auth_url=auth_url,
        expected_state=state,
        listen_host=listen_host,
        listen_port=listen_port,
        timeout_seconds=timeout_seconds,
        open_browser=open_browser,
    )
    code = received.get("code")
    if not code:
        raise OAuthError("OAuth callback did not include an authorization code")

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    payload = {
        "client_id": client_id,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "scope": scope,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    token_response = _post_form(token_url, payload=payload, timeout_seconds=15)
    refresh_token = token_response.get("refresh_token")
    access_token = token_response.get("access_token")
    expires_in = token_response.get("expires_in", 3600)
    granted_scope = token_response.get("scope", scope)
    if not refresh_token:
        raise OAuthError(
            "Microsoft token response did not include refresh_token. "
            "Confirm offline_access was granted."
        )
    if not access_token:
        raise OAuthError(f"Microsoft token exchange failed: {token_response}")
    return OAuthInteractiveResult(
        refresh_token=str(refresh_token),
        access_token=str(access_token),
        expires_at_epoch=int(time.time()) + int(expires_in),
        scope=str(granted_scope),
        raw_response=token_response,
    )


def _build_auth_url(
    *,
    tenant: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
) -> str:
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": scope,
            "state": state,
        }
    )
    return f"{base}?{query}"


def _post_form(url: str, *, payload: dict[str, str], timeout_seconds: int) -> dict[str, object]:
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except Exception as exc:  # pragma: no cover - network path
        raise OAuthError(f"OAuth token request failed: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OAuthError("OAuth token endpoint returned invalid JSON") from exc
    return data


def _wait_for_auth_code(
    *,
    auth_url: str,
    expected_state: str,
    listen_host: str,
    listen_port: int,
    timeout_seconds: int,
    open_browser: bool,
) -> dict[str, str]:
    callback_data: dict[str, str] = {}
    signal = Event()

    class _CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return None

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            callback_data["code"] = (query.get("code") or [""])[0]
            callback_data["state"] = (query.get("state") or [""])[0]
            callback_data["error"] = (query.get("error") or [""])[0]
            status = 200 if callback_data.get("code") else 400
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            if status == 200:
                self.wfile.write(b"Microsoft auth complete. You can close this tab.")
            else:
                self.wfile.write(b"Microsoft auth failed. Check terminal output.")
            signal.set()

    server = HTTPServer((listen_host, listen_port), _CallbackHandler)
    server.timeout = 1
    print(f"Open this URL to authorize Outlook IMAP access:\n{auth_url}")
    if open_browser:
        webbrowser.open(auth_url)

    started = time.time()
    try:
        while not signal.is_set():
            server.handle_request()
            if time.time() - started > timeout_seconds:
                raise OAuthError("Timed out waiting for OAuth callback")
    finally:
        server.server_close()

    if callback_data.get("error"):
        raise OAuthError(f"OAuth authorization failed: {callback_data['error']}")
    if callback_data.get("state") != expected_state:
        raise OAuthError("OAuth state mismatch; possible CSRF or stale callback")
    return callback_data
