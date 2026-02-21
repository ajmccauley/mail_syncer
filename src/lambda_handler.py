from __future__ import annotations

from typing import Any

from src.config import ConfigError, is_dry_run_enabled, load_config
from src.dynamodb_state import (
    DynamoStateError,
    DynamoStateStore,
    DynamoUnavailableError,
)
from src.logging_utils import configure_logging, get_logger
from src.secrets_config import SecretsConfigError
from src.sync_engine import SyncEngine


def _event_dry_run(event: dict[str, Any] | None) -> bool:
    if not isinstance(event, dict) or "dry_run" not in event:
        return is_dry_run_enabled()
    value = event.get("dry_run")
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    logger = get_logger("mail_syncer.lambda")
    try:
        config = load_config()
        configure_logging(config.log_level)
        dry_run = _event_dry_run(event)
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
        # Explicitly fail invocation so CloudWatch/EventBridge shows failed runs.
        raise
    except DynamoStateError as exc:
        logger.error("dynamodb_state_initialization_error", exc_info=exc)
        raise
    except ConfigError as exc:
        logger.error("configuration_error_abort", exc_info=exc)
        raise
    except SecretsConfigError as exc:
        logger.error("secrets_configuration_error_abort", exc_info=exc)
        raise

    return {
        "ok": True,
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
