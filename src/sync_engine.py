from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from src.config import AppConfig
from src.dynamodb_state import DynamoStateStore


@dataclass(frozen=True, slots=True)
class RouteRunResult:
    route_id: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class SyncRunResult:
    run_id: str
    started_at_epoch: int
    finished_at_epoch: int
    routes_processed: int
    route_results: tuple[RouteRunResult, ...]


class SyncEngine:
    def __init__(
        self,
        *,
        config: AppConfig,
        state_store: DynamoStateStore,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.logger = logger

    def run_once(self, *, dry_run: bool) -> SyncRunResult:
        run_id = str(uuid.uuid4())
        started = int(time.time())
        self.logger.info(
            "sync_cycle_started",
            extra={"run_id": run_id},
        )

        # Hard safety barrier: never proceed to any IMAP work without DynamoDB.
        self.state_store.assert_available()

        route_results: list[RouteRunResult] = []
        for route in self.config.routes:
            self.logger.info(
                "route_cycle_started",
                extra={"run_id": run_id, "route_id": route.route_id},
            )
            route_results.append(
                RouteRunResult(
                    route_id=route.route_id,
                    status="pending",
                    detail=(
                        "First batch complete: config + safety gate wired. "
                        "IMAP fetch/append flow not implemented yet."
                    ),
                )
            )
            self.logger.info(
                "route_cycle_finished",
                extra={"run_id": run_id, "route_id": route.route_id},
            )

        finished = int(time.time())
        self.logger.info(
            "sync_cycle_finished",
            extra={"run_id": run_id},
        )
        return SyncRunResult(
            run_id=run_id,
            started_at_epoch=started,
            finished_at_epoch=finished,
            routes_processed=len(route_results),
            route_results=tuple(route_results),
        )

