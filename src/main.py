from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src.config import ConfigError, is_dry_run_enabled, load_config
from src.dynamodb_state import DynamoStateError, DynamoStateStore, DynamoUnavailableError
from src.logging_utils import configure_logging, get_logger
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
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run-once":
        dry_run = bool(args.dry_run or is_dry_run_enabled())
        return _run_cycle(dry_run=dry_run)
    if args.command == "lambda":
        return _run_cycle(dry_run=is_dry_run_enabled())
    parser.error(f"Unknown command: {args.command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
