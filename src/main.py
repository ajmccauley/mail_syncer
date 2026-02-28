from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src.config import ConfigError, is_dry_run_enabled, load_config
from src.dynamodb_state import (
    DynamoStateError,
    DynamoStateStore,
    DynamoUnavailableError,
)
from src.logging_utils import configure_logging, get_logger
from src.oauth_gmail import (
    GMAIL_DEFAULT_SCOPE,
    OAuthError as GmailOAuthError,
    interactive_token_helper as gmail_interactive_token_helper,
)
from src.oauth_microsoft import (
    MS_DEFAULT_SCOPE,
    OAuthError as MicrosoftOAuthError,
    interactive_token_helper as microsoft_interactive_token_helper,
)
from src.secrets_config import SecretsConfigError, resolve_environment
from src.sync_engine import SyncEngine


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gmail to Outlook IMAP sync (DynamoDB-backed state)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once_parser = subparsers.add_parser("run-once", help="Run one sync cycle")
    run_once_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log intended actions without modifying destination",
    )

    subparsers.add_parser(
        "lambda",
        help="Run one Lambda-style sync cycle locally",
    )

    auth_parser = subparsers.add_parser(
        "auth",
        help="Interactive OAuth helper commands",
    )
    auth_subparsers = auth_parser.add_subparsers(dest="auth_provider", required=True)

    auth_gmail = auth_subparsers.add_parser(
        "gmail", help="Run Gmail OAuth consent flow"
    )
    auth_gmail.add_argument("--client-id")
    auth_gmail.add_argument("--client-secret")
    auth_gmail.add_argument("--scope", default=GMAIL_DEFAULT_SCOPE)
    auth_gmail.add_argument("--listen-host", default="127.0.0.1")
    auth_gmail.add_argument("--listen-port", type=int, default=8765)
    auth_gmail.add_argument("--timeout-seconds", type=int, default=180)
    auth_gmail.add_argument("--no-browser", action="store_true")
    auth_gmail.add_argument("--write-parameter-name")
    auth_gmail.add_argument("--write-parameter-key", default="GMAIL_REFRESH_TOKEN")
    auth_gmail.add_argument(
        "--write-secret-id",
        help="Deprecated: write refresh token to Secrets Manager JSON secret",
    )
    auth_gmail.add_argument("--write-secret-key", default="GMAIL_REFRESH_TOKEN")
    auth_gmail.add_argument("--aws-region")

    auth_microsoft = auth_subparsers.add_parser(
        "microsoft", help="Run Microsoft OAuth consent flow"
    )
    auth_microsoft.add_argument("--tenant", default=None)
    auth_microsoft.add_argument("--client-id")
    auth_microsoft.add_argument("--client-secret", default=None)
    auth_microsoft.add_argument("--scope", default=MS_DEFAULT_SCOPE)
    auth_microsoft.add_argument("--listen-host", default="localhost")
    auth_microsoft.add_argument("--listen-port", type=int, default=8766)
    auth_microsoft.add_argument("--timeout-seconds", type=int, default=180)
    auth_microsoft.add_argument("--no-browser", action="store_true")
    auth_microsoft.add_argument("--write-parameter-name")
    auth_microsoft.add_argument("--write-parameter-key", default="MS_REFRESH_TOKEN")
    auth_microsoft.add_argument(
        "--write-secret-id",
        help="Deprecated: write refresh token to Secrets Manager JSON secret",
    )
    auth_microsoft.add_argument("--write-secret-key", default="MS_REFRESH_TOKEN")
    auth_microsoft.add_argument("--aws-region")
    return parser


def _run_cycle(*, dry_run: bool) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    configure_logging(config.log_level)
    logger = get_logger("mail_syncer")
    logger.info("startup", extra={"run_id": "bootstrap"})

    try:
        engine = SyncEngine(
            config=config,
            state_store=DynamoStateStore(
                table_name=config.dynamodb_table,
                region_name=config.aws_region,
            ),
            logger=logger,
        )
        result = engine.run_once(dry_run=dry_run)
    except DynamoUnavailableError as exc:
        logger.error("dynamodb_unavailable_abort", exc_info=exc)
        return 3
    except DynamoStateError as exc:
        logger.error("dynamodb_state_initialization_error", exc_info=exc)
        return 3

    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "routes_processed": result.routes_processed,
                "dry_run": dry_run,
                "route_results": [
                    {
                        "route_id": route.route_id,
                        "status": route.status,
                        "copied": route.copied,
                        "skipped_duplicates": route.skipped_duplicates,
                        "failed": route.failed,
                    }
                    for route in result.route_results
                ],
            }
        )
    )
    return 0


def _secrets_client(*, region_name: str | None) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required for writing AWS Secrets Manager values"
        ) from exc
    kwargs: dict[str, Any] = {}
    if region_name:
        kwargs["region_name"] = region_name
    return boto3.client("secretsmanager", **kwargs)


def _ssm_client(*, region_name: str | None) -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required for writing AWS SSM Parameter Store values"
        ) from exc
    kwargs: dict[str, Any] = {}
    if region_name:
        kwargs["region_name"] = region_name
    return boto3.client("ssm", **kwargs)


def _load_json_object(raw: str, *, source: str) -> dict[str, Any]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{source} must contain a JSON object: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"{source} must contain a JSON object")
    return loaded


def _is_ssm_parameter_not_found(*, client: Any, exc: Exception) -> bool:
    exceptions = getattr(client, "exceptions", None)
    if exceptions is None:
        return False
    parameter_not_found = getattr(exceptions, "ParameterNotFound", None)
    if parameter_not_found is None:
        return False
    return isinstance(exc, parameter_not_found)


def _write_secret_key(
    *,
    secret_id: str,
    key: str,
    value: str,
    region_name: str | None,
) -> None:
    client = _secrets_client(region_name=region_name)
    current: dict[str, Any] = {}
    try:
        response = client.get_secret_value(SecretId=secret_id)
        secret_string = response.get("SecretString", "{}")
        current = _load_json_object(secret_string, source=f"secret {secret_id}")
    except Exception:
        # If secret read fails, write will likely fail too; we still attempt and surface
        # the final error to the caller.
        current = {}

    current[key] = value
    client.put_secret_value(
        SecretId=secret_id,
        SecretString=json.dumps(current, separators=(",", ":")),
    )


def _write_parameter_key(
    *,
    parameter_name: str,
    key: str,
    value: str,
    region_name: str | None,
) -> None:
    client = _ssm_client(region_name=region_name)
    current: dict[str, Any] = {}
    try:
        response = client.get_parameter(Name=parameter_name, WithDecryption=True)
    except Exception as exc:
        if not _is_ssm_parameter_not_found(client=client, exc=exc):
            raise
    else:
        parameter_value = response.get("Parameter", {}).get("Value", "{}")
        current = _load_json_object(
            str(parameter_value),
            source=f"parameter {parameter_name}",
        )

    current[key] = value
    client.put_parameter(
        Name=parameter_name,
        Type="SecureString",
        Value=json.dumps(current, separators=(",", ":")),
        Overwrite=True,
    )


def _resolve_token_store(
    args: argparse.Namespace,
    *,
    default_key: str,
) -> tuple[str, str, str] | None:
    parameter_name = (args.write_parameter_name or "").strip()
    secret_id = (args.write_secret_id or "").strip()
    if parameter_name and secret_id:
        raise ValueError(
            "Use only one output target: --write-parameter-name or --write-secret-id."
        )
    if parameter_name:
        return ("parameter", parameter_name, args.write_parameter_key or default_key)
    if secret_id:
        return ("secret", secret_id, args.write_secret_key or default_key)
    return None


def _run_auth_gmail(args: argparse.Namespace) -> int:
    try:
        env = resolve_environment()
    except SecretsConfigError as exc:
        print(f"Secrets config error: {exc}", file=sys.stderr)
        return 2
    client_id = args.client_id or env.get("GMAIL_CLIENT_ID")
    client_secret = args.client_secret or env.get("GMAIL_CLIENT_SECRET")
    if not client_id or not client_secret:
        print(
            "Missing Gmail client credentials. Provide --client-id/--client-secret "
            "or set GMAIL_CLIENT_ID/GMAIL_CLIENT_SECRET.",
            file=sys.stderr,
        )
        return 2

    try:
        result = gmail_interactive_token_helper(
            client_id=client_id,
            client_secret=client_secret,
            scope=args.scope,
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            timeout_seconds=args.timeout_seconds,
            open_browser=not args.no_browser,
        )
    except GmailOAuthError as exc:
        print(f"Gmail OAuth error: {exc}", file=sys.stderr)
        return 1

    try:
        token_store = _resolve_token_store(args, default_key="GMAIL_REFRESH_TOKEN")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if token_store:
        store_type, destination, key = token_store
        try:
            if store_type == "parameter":
                _write_parameter_key(
                    parameter_name=destination,
                    key=key,
                    value=result.refresh_token,
                    region_name=args.aws_region or env.get("AWS_REGION"),
                )
            else:
                _write_secret_key(
                    secret_id=destination,
                    key=key,
                    value=result.refresh_token,
                    region_name=args.aws_region or env.get("AWS_REGION"),
                )
        except Exception as exc:
            print(f"Failed to persist token: {exc}", file=sys.stderr)
            return 1
    else:
        key = args.write_parameter_key

    print(
        json.dumps(
            {
                "provider": "gmail",
                "refresh_token": result.refresh_token,
                "access_token": result.access_token,
                "expires_at_epoch": result.expires_at_epoch,
                "scope": result.scope,
                "env_export": f"{key}={result.refresh_token}",
                "parameter_updated": bool(
                    token_store and token_store[0] == "parameter"
                ),
                "parameter_name": (
                    token_store[1]
                    if token_store and token_store[0] == "parameter"
                    else None
                ),
                "secret_updated": bool(token_store and token_store[0] == "secret"),
                "secret_id": (
                    token_store[1]
                    if token_store and token_store[0] == "secret"
                    else None
                ),
            }
        )
    )
    return 0


def _run_auth_microsoft(args: argparse.Namespace) -> int:
    try:
        env = resolve_environment()
    except SecretsConfigError as exc:
        print(f"Secrets config error: {exc}", file=sys.stderr)
        return 2
    tenant = args.tenant or env.get("MS_TENANT") or "consumers"
    client_id = args.client_id or env.get("MS_CLIENT_ID")
    client_secret = args.client_secret or env.get("MS_CLIENT_SECRET")
    if not client_id:
        print(
            "Missing Microsoft client ID. Provide --client-id or set MS_CLIENT_ID.",
            file=sys.stderr,
        )
        return 2

    try:
        result = microsoft_interactive_token_helper(
            tenant=tenant,
            client_id=client_id,
            client_secret=client_secret,
            scope=args.scope,
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            timeout_seconds=args.timeout_seconds,
            open_browser=not args.no_browser,
        )
    except MicrosoftOAuthError as exc:
        print(f"Microsoft OAuth error: {exc}", file=sys.stderr)
        return 1

    try:
        token_store = _resolve_token_store(args, default_key="MS_REFRESH_TOKEN")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if token_store:
        store_type, destination, key = token_store
        try:
            if store_type == "parameter":
                _write_parameter_key(
                    parameter_name=destination,
                    key=key,
                    value=result.refresh_token,
                    region_name=args.aws_region or env.get("AWS_REGION"),
                )
            else:
                _write_secret_key(
                    secret_id=destination,
                    key=key,
                    value=result.refresh_token,
                    region_name=args.aws_region or env.get("AWS_REGION"),
                )
        except Exception as exc:
            print(f"Failed to persist token: {exc}", file=sys.stderr)
            return 1
    else:
        key = args.write_parameter_key

    print(
        json.dumps(
            {
                "provider": "microsoft",
                "refresh_token": result.refresh_token,
                "access_token": result.access_token,
                "expires_at_epoch": result.expires_at_epoch,
                "scope": result.scope,
                "env_export": f"{key}={result.refresh_token}",
                "parameter_updated": bool(
                    token_store and token_store[0] == "parameter"
                ),
                "parameter_name": (
                    token_store[1]
                    if token_store and token_store[0] == "parameter"
                    else None
                ),
                "secret_updated": bool(token_store and token_store[0] == "secret"),
                "secret_id": (
                    token_store[1]
                    if token_store and token_store[0] == "secret"
                    else None
                ),
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SecretsConfigError as exc:
        print(f"Secrets config error: {exc}", file=sys.stderr)
        return 2
    if args.command == "run-once":
        try:
            dry_run = bool(args.dry_run or is_dry_run_enabled())
        except SecretsConfigError as exc:
            print(f"Secrets config error: {exc}", file=sys.stderr)
            return 2
        return _run_cycle(dry_run=dry_run)
    if args.command == "lambda":
        try:
            dry_run = is_dry_run_enabled()
        except SecretsConfigError as exc:
            print(f"Secrets config error: {exc}", file=sys.stderr)
            return 2
        return _run_cycle(dry_run=dry_run)
    if args.command == "auth" and args.auth_provider == "gmail":
        return _run_auth_gmail(args)
    if args.command == "auth" and args.auth_provider == "microsoft":
        return _run_auth_microsoft(args)
    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
