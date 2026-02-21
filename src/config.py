from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when required runtime configuration is invalid or missing."""


@dataclass(frozen=True, slots=True)
class RouteConfig:
    gmail_email: str
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    outlook_email: str
    outlook_target_folder: str
    create_target_folder: bool = False

    @property
    def route_id(self) -> str:
        return (
            f"gmail={self.gmail_email}"
            f"|outlook={self.outlook_email}"
            f"|folder={self.outlook_target_folder}"
        )


@dataclass(frozen=True, slots=True)
class AppConfig:
    aws_region: str
    dynamodb_table: str
    outlook_email: str
    ms_client_id: str
    ms_client_secret: str | None
    ms_tenant: str
    ms_refresh_token: str
    sync_interval_seconds: int
    uidvalidity_resync_hours: int
    uid_record_ttl_days: int
    fail_record_ttl_days: int
    imap_timeout_seconds: int
    imap_max_retries: int
    imap_retry_base_seconds: float
    gmail_imap_host: str
    gmail_imap_port: int
    outlook_imap_host: str
    outlook_imap_port: int
    log_level: str
    routes: tuple[RouteConfig, ...]

    @property
    def route_count(self) -> int:
        return len(self.routes)


def _env(name: str, env: dict[str, str], default: str | None = None) -> str | None:
    value = env.get(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _required(name: str, env: dict[str, str]) -> str:
    value = _env(name, env)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _parse_float(name: str, raw: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _load_routes_from_json(raw: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in SYNC_ROUTES_JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise ConfigError("SYNC_ROUTES_JSON must be a JSON array of route objects")
    if not all(isinstance(route, dict) for route in payload):
        raise ConfigError("Each route in SYNC_ROUTES_JSON must be a JSON object")
    return payload


def _load_routes_from_file(path_value: str) -> list[dict[str, Any]]:
    path = Path(path_value)
    if not path.exists():
        raise ConfigError(f"SYNC_ROUTES_FILE does not exist: {path}")
    raw = path.read_text(encoding="utf-8")
    return _load_routes_from_json(raw)


def _route_from_object(
    route_obj: dict[str, Any],
    *,
    default_outlook_email: str,
    env: dict[str, str],
) -> RouteConfig:
    gmail_email = str(route_obj.get("gmail_email") or "").strip() or _required(
        "GMAIL_EMAIL", env
    )
    outlook_target_folder = str(route_obj.get("outlook_target_folder") or "").strip() or _required(
        "OUTLOOK_TARGET_FOLDER", env
    )
    outlook_email = str(route_obj.get("outlook_email") or "").strip() or default_outlook_email

    gmail_client_id = str(route_obj.get("gmail_client_id") or "").strip() or _required(
        "GMAIL_CLIENT_ID", env
    )
    gmail_client_secret = str(route_obj.get("gmail_client_secret") or "").strip() or _required(
        "GMAIL_CLIENT_SECRET", env
    )
    gmail_refresh_token = str(route_obj.get("gmail_refresh_token") or "").strip() or _required(
        "GMAIL_REFRESH_TOKEN", env
    )
    create_target_folder = _parse_bool(
        str(route_obj.get("create_target_folder"))
        if "create_target_folder" in route_obj
        else None
    )
    return RouteConfig(
        gmail_email=gmail_email,
        gmail_client_id=gmail_client_id,
        gmail_client_secret=gmail_client_secret,
        gmail_refresh_token=gmail_refresh_token,
        outlook_email=outlook_email,
        outlook_target_folder=outlook_target_folder,
        create_target_folder=create_target_folder,
    )


def _load_route_objects(env: dict[str, str]) -> list[dict[str, Any]]:
    routes_json = _env("SYNC_ROUTES_JSON", env)
    if routes_json:
        return _load_routes_from_json(routes_json)

    routes_file = _env("SYNC_ROUTES_FILE", env)
    if routes_file:
        return _load_routes_from_file(routes_file)

    # Backward-compatible single route mode.
    return [
        {
            "gmail_email": _required("GMAIL_EMAIL", env),
            "outlook_target_folder": _required("OUTLOOK_TARGET_FOLDER", env),
            "gmail_client_id": _required("GMAIL_CLIENT_ID", env),
            "gmail_client_secret": _required("GMAIL_CLIENT_SECRET", env),
            "gmail_refresh_token": _required("GMAIL_REFRESH_TOKEN", env),
        }
    ]


def load_config(env: dict[str, str] | None = None) -> AppConfig:
    current_env = dict(os.environ if env is None else env)
    outlook_email = _required("OUTLOOK_EMAIL", current_env)

    route_objects = _load_route_objects(current_env)
    if not route_objects:
        raise ConfigError("At least one route must be provided")

    routes = tuple(
        _route_from_object(
            route_obj,
            default_outlook_email=outlook_email,
            env=current_env,
        )
        for route_obj in route_objects
    )
    for route in routes:
        if route.outlook_email != outlook_email:
            raise ConfigError(
                "All routes must target one shared Outlook mailbox; "
                f"expected {outlook_email}, found {route.outlook_email}"
            )

    sync_interval_raw = _env("SYNC_INTERVAL_SECONDS", current_env, "300") or "300"
    try:
        sync_interval_seconds = int(sync_interval_raw)
    except ValueError as exc:
        raise ConfigError("SYNC_INTERVAL_SECONDS must be an integer") from exc
    if sync_interval_seconds <= 0:
        raise ConfigError("SYNC_INTERVAL_SECONDS must be greater than zero")

    uidvalidity_resync_hours = _parse_int(
        "UIDVALIDITY_RESYNC_HOURS",
        _env("UIDVALIDITY_RESYNC_HOURS", current_env, "24") or "24",
    )
    if uidvalidity_resync_hours <= 0:
        raise ConfigError("UIDVALIDITY_RESYNC_HOURS must be greater than zero")

    uid_record_ttl_days = _parse_int(
        "UID_RECORD_TTL_DAYS",
        _env("UID_RECORD_TTL_DAYS", current_env, "365") or "365",
    )
    if uid_record_ttl_days <= 0:
        raise ConfigError("UID_RECORD_TTL_DAYS must be greater than zero")

    fail_record_ttl_days = _parse_int(
        "FAIL_RECORD_TTL_DAYS",
        _env("FAIL_RECORD_TTL_DAYS", current_env, "14") or "14",
    )
    if fail_record_ttl_days <= 0:
        raise ConfigError("FAIL_RECORD_TTL_DAYS must be greater than zero")

    imap_timeout_seconds = _parse_int(
        "IMAP_TIMEOUT_SECONDS",
        _env("IMAP_TIMEOUT_SECONDS", current_env, "30") or "30",
    )
    if imap_timeout_seconds <= 0:
        raise ConfigError("IMAP_TIMEOUT_SECONDS must be greater than zero")

    imap_max_retries = _parse_int(
        "IMAP_MAX_RETRIES", _env("IMAP_MAX_RETRIES", current_env, "3") or "3"
    )
    if imap_max_retries <= 0:
        raise ConfigError("IMAP_MAX_RETRIES must be greater than zero")

    imap_retry_base_seconds = _parse_float(
        "IMAP_RETRY_BASE_SECONDS",
        _env("IMAP_RETRY_BASE_SECONDS", current_env, "1.0") or "1.0",
    )
    if imap_retry_base_seconds <= 0:
        raise ConfigError("IMAP_RETRY_BASE_SECONDS must be greater than zero")

    gmail_imap_host = _env("GMAIL_IMAP_HOST", current_env, "imap.gmail.com") or "imap.gmail.com"
    gmail_imap_port = _parse_int("GMAIL_IMAP_PORT", _env("GMAIL_IMAP_PORT", current_env, "993") or "993")
    outlook_imap_host = (
        _env("OUTLOOK_IMAP_HOST", current_env, "outlook.office365.com")
        or "outlook.office365.com"
    )
    outlook_imap_port = _parse_int(
        "OUTLOOK_IMAP_PORT", _env("OUTLOOK_IMAP_PORT", current_env, "993") or "993"
    )

    return AppConfig(
        aws_region=_required("AWS_REGION", current_env),
        dynamodb_table=_required("DYNAMODB_TABLE", current_env),
        outlook_email=outlook_email,
        ms_client_id=_required("MS_CLIENT_ID", current_env),
        ms_client_secret=_env("MS_CLIENT_SECRET", current_env),
        ms_tenant=_env("MS_TENANT", current_env, "consumers") or "consumers",
        ms_refresh_token=_required("MS_REFRESH_TOKEN", current_env),
        sync_interval_seconds=sync_interval_seconds,
        uidvalidity_resync_hours=uidvalidity_resync_hours,
        uid_record_ttl_days=uid_record_ttl_days,
        fail_record_ttl_days=fail_record_ttl_days,
        imap_timeout_seconds=imap_timeout_seconds,
        imap_max_retries=imap_max_retries,
        imap_retry_base_seconds=imap_retry_base_seconds,
        gmail_imap_host=gmail_imap_host,
        gmail_imap_port=gmail_imap_port,
        outlook_imap_host=outlook_imap_host,
        outlook_imap_port=outlook_imap_port,
        log_level=_env("LOG_LEVEL", current_env, "INFO") or "INFO",
        routes=routes,
    )


def is_dry_run_enabled(env: dict[str, str] | None = None) -> bool:
    current_env = dict(os.environ if env is None else env)
    return _parse_bool(_env("DRY_RUN", current_env), default=False)
