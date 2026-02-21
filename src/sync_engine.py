from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.config import AppConfig, RouteConfig
from src.dynamodb_state import DynamoStateStore
from src.gmail_imap import GmailImapClient, GmailImapError
from src.imap_utils import extract_message_id, rfc822_sha256
from src.oauth_gmail import refresh_access_token as refresh_gmail_access_token
from src.oauth_microsoft import refresh_access_token as refresh_ms_access_token
from src.outlook_imap import OutlookImapClient, OutlookImapError


@dataclass(frozen=True, slots=True)
class RouteRunResult:
    route_id: str
    status: str
    copied: int
    skipped_duplicates: int
    failed: int
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
        gmail_refresh_fn: Callable[..., Any] = refresh_gmail_access_token,
        ms_refresh_fn: Callable[..., Any] = refresh_ms_access_token,
        gmail_client_factory: Callable[..., GmailImapClient] = GmailImapClient,
        outlook_client_factory: Callable[..., OutlookImapClient] = OutlookImapClient,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.logger = logger
        self.gmail_refresh_fn = gmail_refresh_fn
        self.ms_refresh_fn = ms_refresh_fn
        self.gmail_client_factory = gmail_client_factory
        self.outlook_client_factory = outlook_client_factory
        self.sleep_fn = sleep_fn

    def run_once(self, *, dry_run: bool) -> SyncRunResult:
        run_id = str(uuid.uuid4())
        started = int(time.time())
        self.logger.info("sync_cycle_started", extra={"run_id": run_id})

        # Hard safety barrier: never proceed to any IMAP work without DynamoDB.
        self.state_store.assert_available()

        outlook_access_token = self._with_retry(
            lambda: (
                self.ms_refresh_fn(
                    tenant=self.config.ms_tenant,
                    client_id=self.config.ms_client_id,
                    client_secret=self.config.ms_client_secret,
                    refresh_token=self.config.ms_refresh_token,
                ).access_token
            ),
            operation_name="ms_access_token_refresh",
            run_id=run_id,
            route_id=None,
        )

        outlook_client = self.outlook_client_factory(
            email_address=self.config.outlook_email,
            access_token=outlook_access_token,
            host=self.config.outlook_imap_host,
            port=self.config.outlook_imap_port,
            timeout_seconds=self.config.imap_timeout_seconds,
        )
        self._with_retry(
            outlook_client.connect,
            operation_name="outlook_connect",
            run_id=run_id,
            route_id=None,
        )

        route_results: list[RouteRunResult] = []
        try:
            for route in self.config.routes:
                try:
                    route_results.append(
                        self._run_route(
                            route=route,
                            outlook_client=outlook_client,
                            run_id=run_id,
                            dry_run=dry_run,
                        )
                    )
                except Exception as exc:
                    self.logger.error(
                        "route_cycle_failed",
                        extra={"run_id": run_id, "route_id": route.route_id},
                        exc_info=exc,
                    )
                    route_results.append(
                        RouteRunResult(
                            route_id=route.route_id,
                            status="route_error",
                            copied=0,
                            skipped_duplicates=0,
                            failed=1,
                            detail=str(exc),
                        )
                    )
        finally:
            outlook_client.close()

        finished = int(time.time())
        self.logger.info("sync_cycle_finished", extra={"run_id": run_id})
        return SyncRunResult(
            run_id=run_id,
            started_at_epoch=started,
            finished_at_epoch=finished,
            routes_processed=len(route_results),
            route_results=tuple(route_results),
        )

    def _run_route(
        self,
        *,
        route: RouteConfig,
        outlook_client: OutlookImapClient,
        run_id: str,
        dry_run: bool,
    ) -> RouteRunResult:
        self.logger.info(
            "route_cycle_started",
            extra={"run_id": run_id, "route_id": route.route_id},
        )
        pk = self.state_store.route_pk(
            gmail_email=route.gmail_email,
            outlook_email=route.outlook_email,
            folder=route.outlook_target_folder,
        )
        watermark = self.state_store.get_watermark(pk=pk)

        gmail_access_token = self._with_retry(
            lambda: (
                self.gmail_refresh_fn(
                    client_id=route.gmail_client_id,
                    client_secret=route.gmail_client_secret,
                    refresh_token=route.gmail_refresh_token,
                ).access_token
            ),
            operation_name="gmail_access_token_refresh",
            run_id=run_id,
            route_id=route.route_id,
        )

        gmail_client = self.gmail_client_factory(
            email_address=route.gmail_email,
            access_token=gmail_access_token,
            host=self.config.gmail_imap_host,
            port=self.config.gmail_imap_port,
            timeout_seconds=self.config.imap_timeout_seconds,
        )

        copied = 0
        skipped_duplicates = 0
        failed = 0
        processed_uids: list[int] = []
        failed_uids: list[int] = []
        try:
            self._with_retry(
                gmail_client.connect,
                operation_name="gmail_connect",
                run_id=run_id,
                route_id=route.route_id,
            )
            self._with_retry(
                lambda: outlook_client.ensure_folder(
                    route.outlook_target_folder,
                    create_if_missing=route.create_target_folder,
                ),
                operation_name="outlook_ensure_folder",
                run_id=run_id,
                route_id=route.route_id,
            )

            current_uidvalidity = self._with_retry(
                gmail_client.get_uidvalidity,
                operation_name="gmail_get_uidvalidity",
                run_id=run_id,
                route_id=route.route_id,
            )

            uidvalidity_changed = (
                watermark.uidvalidity is not None
                and watermark.uidvalidity != current_uidvalidity
            )
            if uidvalidity_changed:
                since_date = (
                    datetime.now(timezone.utc)
                    - timedelta(hours=self.config.uidvalidity_resync_hours)
                ).date()
                candidate_uids = self._with_retry(
                    lambda: gmail_client.search_uids_since(since_date=since_date),
                    operation_name="gmail_search_since",
                    run_id=run_id,
                    route_id=route.route_id,
                )
            else:
                candidate_uids = self._with_retry(
                    lambda: gmail_client.search_uids_after(last_uid=watermark.last_uid),
                    operation_name="gmail_search_after",
                    run_id=run_id,
                    route_id=route.route_id,
                )

            for uid in candidate_uids:
                processed_uids.append(uid)
                raw_rfc822 = self._with_retry(
                    lambda uid_value=uid: gmail_client.fetch_rfc822(uid=uid_value),
                    operation_name="gmail_fetch_rfc822",
                    run_id=run_id,
                    route_id=route.route_id,
                )
                message_id = extract_message_id(raw_rfc822)
                payload_hash = rfc822_sha256(raw_rfc822)

                if uidvalidity_changed and self.state_store.payload_already_copied(
                    pk=pk,
                    message_id_header=message_id,
                    rfc822_sha256=payload_hash,
                ):
                    skipped_duplicates += 1
                    self.logger.info(
                        "resync_duplicate_detected",
                        extra={"run_id": run_id, "route_id": route.route_id},
                    )
                    continue

                if dry_run:
                    if self.state_store.uid_record_exists(
                        pk=pk,
                        uidvalidity=current_uidvalidity,
                        gmail_uid=uid,
                    ):
                        skipped_duplicates += 1
                        self.logger.info(
                            "dry_run_duplicate_skip",
                            extra={"run_id": run_id, "route_id": route.route_id},
                        )
                    else:
                        self.logger.info(
                            "dry_run_would_copy",
                            extra={"run_id": run_id, "route_id": route.route_id},
                        )
                    continue

                claimed = self.state_store.claim_uid_copy(
                    pk=pk,
                    uidvalidity=current_uidvalidity,
                    gmail_uid=uid,
                )
                if not claimed:
                    skipped_duplicates += 1
                    self.logger.info(
                        "uid_already_claimed_or_done_skip",
                        extra={"run_id": run_id, "route_id": route.route_id},
                    )
                    continue

                try:
                    self._with_retry(
                        lambda raw=raw_rfc822: outlook_client.append_rfc822(
                            folder_name=route.outlook_target_folder,
                            raw_rfc822=raw,
                        ),
                        operation_name="outlook_append",
                        run_id=run_id,
                        route_id=route.route_id,
                    )
                    self.state_store.finalize_uid_copy(
                        pk=pk,
                        uidvalidity=current_uidvalidity,
                        gmail_uid=uid,
                        message_id_header=message_id,
                        rfc822_sha256=payload_hash,
                        ttl_days=self.config.uid_record_ttl_days,
                    )
                    copied += 1
                except Exception as exc:
                    failed += 1
                    failed_uids.append(uid)
                    self.state_store.abandon_pending_uid(
                        pk=pk,
                        uidvalidity=current_uidvalidity,
                        gmail_uid=uid,
                    )
                    self.state_store.record_failure(
                        pk=pk,
                        uidvalidity=current_uidvalidity,
                        gmail_uid=uid,
                        error_message=str(exc),
                        ttl_days=self.config.fail_record_ttl_days,
                    )
                    self.logger.error(
                        "message_copy_failed_continue",
                        extra={"run_id": run_id, "route_id": route.route_id},
                        exc_info=exc,
                    )
                    continue

            if not dry_run:
                new_last_uid = watermark.last_uid
                if processed_uids:
                    if failed_uids:
                        # Keep replay window at first failed UID so retries can recover.
                        new_last_uid = max(watermark.last_uid, min(failed_uids) - 1)
                    else:
                        new_last_uid = max(watermark.last_uid, max(processed_uids))
                self.state_store.set_watermark(
                    pk=pk,
                    uidvalidity=current_uidvalidity,
                    last_uid=new_last_uid,
                )

            status = "ok" if failed == 0 else "partial_failure"
            detail = f"copied={copied}, skipped_duplicates={skipped_duplicates}, failed={failed}"
            return RouteRunResult(
                route_id=route.route_id,
                status=status,
                copied=copied,
                skipped_duplicates=skipped_duplicates,
                failed=failed,
                detail=detail,
            )
        finally:
            gmail_client.close()
            self.logger.info(
                "route_cycle_finished",
                extra={"run_id": run_id, "route_id": route.route_id},
            )

    def _with_retry(
        self,
        fn: Callable[[], Any],
        *,
        operation_name: str,
        run_id: str,
        route_id: str | None,
    ) -> Any:
        max_attempts = max(1, self.config.imap_max_retries)
        delay = self.config.imap_retry_base_seconds
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return fn()
            except (
                GmailImapError,
                OutlookImapError,
                OSError,
                TimeoutError,
                RuntimeError,
            ) as exc:
                last_exc = exc
                self.logger.warning(
                    "operation_retryable_error",
                    extra={"run_id": run_id, "route_id": route_id},
                    exc_info=exc,
                )
                if attempt >= max_attempts:
                    break
                self.sleep_fn(delay)
                delay *= 2
        assert last_exc is not None
        raise last_exc
