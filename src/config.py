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

    return AppConfig(
        aws_region=_required("AWS_REGION", current_env),
        dynamodb_table=_required("DYNAMODB_TABLE", current_env),
        outlook_email=outlook_email,
        ms_client_id=_required("MS_CLIENT_ID", current_env),
        ms_client_secret=_env("MS_CLIENT_SECRET", current_env),
        ms_tenant=_env("MS_TENANT", current_env, "consumers") or "consumers",
        ms_refresh_token=_required("MS_REFRESH_TOKEN", current_env),
        sync_interval_seconds=sync_interval_seconds,
        log_level=_env("LOG_LEVEL", current_env, "INFO") or "INFO",
        routes=routes,
    )


def is_dry_run_enabled(env: dict[str, str] | None = None) -> bool:
    current_env = dict(os.environ if env is None else env)
    return _parse_bool(_env("DRY_RUN", current_env), default=False)
