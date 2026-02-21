from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


class DynamoStateError(RuntimeError):
    """Base class for DynamoDB state-layer errors."""


class DynamoUnavailableError(DynamoStateError):
    """Raised when DynamoDB cannot be reached and sync must fail safe."""


@dataclass(frozen=True, slots=True)
class Watermark:
    uidvalidity: int | None
    last_uid: int


def _now_epoch() -> int:
    return int(time.time())


def _s(value: str) -> dict[str, str]:
    return {"S": value}


def _n(value: int) -> dict[str, str]:
    return {"N": str(int(value))}


def _get_s(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    if not isinstance(value, dict):
        return None
    if "S" in value:
        return str(value["S"])
    return None


def _get_n(item: dict[str, Any], key: str) -> int | None:
    value = item.get(key)
    if not isinstance(value, dict):
        return None
    raw = value.get("N")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _is_conditional_failure(exc: Exception) -> bool:
    error = getattr(exc, "response", {})
    if not isinstance(error, dict):
        return False
    details = error.get("Error", {})
    if not isinstance(details, dict):
        return False
    return details.get("Code") == "ConditionalCheckFailedException"


class DynamoStateStore:
    def __init__(
        self,
        *,
        table_name: str,
        region_name: str,
        client: Any | None = None,
    ) -> None:
        self.table_name = table_name
        self.region_name = region_name
        self._client = client or self._make_default_client(region_name=region_name)

    @staticmethod
    def _make_default_client(*, region_name: str) -> Any:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover
            raise DynamoStateError("boto3 is required for DynamoDB state access") from exc
        return boto3.client("dynamodb", region_name=region_name)

    @staticmethod
    def route_pk(*, gmail_email: str, outlook_email: str, folder: str) -> str:
        return f"ROUTE#{gmail_email}#DEST#{outlook_email}#FOLDER#{folder}"

    @staticmethod
    def uid_sk(*, uidvalidity: int, gmail_uid: int) -> str:
        return f"UID#{uidvalidity}#{gmail_uid}"

    @staticmethod
    def fail_sk(*, uidvalidity: int, gmail_uid: int) -> str:
        return f"FAIL#{uidvalidity}#{gmail_uid}"

    def _key(self, *, pk: str, sk: str) -> dict[str, dict[str, str]]:
        return {"PK": _s(pk), "SK": _s(sk)}

    def assert_available(self) -> None:
        """
        Validate that DynamoDB is reachable before any IMAP action occurs.

        This is the critical fail-safe guardrail required by the sync design.
        """
        try:
            response = self._client.describe_table(TableName=self.table_name)
        except Exception as exc:
            raise DynamoUnavailableError(
                f"DynamoDB unavailable for table {self.table_name}: {exc}"
            ) from exc
        status = (
            response.get("Table", {}).get("TableStatus")
            if isinstance(response, dict)
            else None
        )
        if not status:
            raise DynamoUnavailableError(
                f"DynamoDB describe_table returned no status for {self.table_name}"
            )

    def get_watermark(self, *, pk: str) -> Watermark:
        try:
            response = self._client.get_item(
                TableName=self.table_name,
                Key=self._key(pk=pk, sk="WATERMARK"),
                ConsistentRead=True,
            )
        except Exception as exc:
            raise DynamoStateError(f"Failed to get watermark: {exc}") from exc
        item = response.get("Item", {}) if isinstance(response, dict) else {}
        uidvalidity = _get_n(item, "uidvalidity")
        last_uid = _get_n(item, "last_uid") or 0
        return Watermark(uidvalidity=uidvalidity, last_uid=last_uid)

    def set_watermark(self, *, pk: str, uidvalidity: int, last_uid: int) -> None:
        try:
            self._client.put_item(
                TableName=self.table_name,
                Item={
                    "PK": _s(pk),
                    "SK": _s("WATERMARK"),
                    "uidvalidity": _n(uidvalidity),
                    "last_uid": _n(last_uid),
                    "updated_at": _n(_now_epoch()),
                },
            )
        except Exception as exc:
            raise DynamoStateError(f"Failed to set watermark: {exc}") from exc

    def uid_record_exists(self, *, pk: str, uidvalidity: int, gmail_uid: int) -> bool:
        try:
            response = self._client.get_item(
                TableName=self.table_name,
                Key=self._key(pk=pk, sk=self.uid_sk(uidvalidity=uidvalidity, gmail_uid=gmail_uid)),
                ConsistentRead=True,
            )
        except Exception as exc:
            raise DynamoStateError(f"Failed to check UID record: {exc}") from exc
        item = response.get("Item", {}) if isinstance(response, dict) else {}
        return bool(item)

    def claim_uid_copy(self, *, pk: str, uidvalidity: int, gmail_uid: int) -> bool:
        sk = self.uid_sk(uidvalidity=uidvalidity, gmail_uid=gmail_uid)
        now = _now_epoch()
        try:
            self._client.put_item(
                TableName=self.table_name,
                Item={
                    "PK": _s(pk),
                    "SK": _s(sk),
                    "status": _s("PENDING"),
                    "created_at": _n(now),
                    "updated_at": _n(now),
                },
                ConditionExpression="attribute_not_exists(SK)",
            )
        except Exception as exc:
            if _is_conditional_failure(exc):
                return False
            raise DynamoStateError(f"Failed to claim UID copy: {exc}") from exc
        return True

    def finalize_uid_copy(
        self,
        *,
        pk: str,
        uidvalidity: int,
        gmail_uid: int,
        message_id_header: str | None,
        rfc822_sha256: str,
        ttl_days: int,
    ) -> None:
        sk = self.uid_sk(uidvalidity=uidvalidity, gmail_uid=gmail_uid)
        now = _now_epoch()
        ttl = now + (ttl_days * 86400)
        item = {
            "PK": _s(pk),
            "SK": _s(sk),
            "status": _s("DONE"),
            "copied_at": _n(now),
            "updated_at": _n(now),
            "rfc822_sha256": _s(rfc822_sha256),
            "ttl": _n(ttl),
        }
        if message_id_header:
            item["message_id_header"] = _s(message_id_header)
        try:
            self._client.put_item(
                TableName=self.table_name,
                Item=item,
            )
        except Exception as exc:
            raise DynamoStateError(f"Failed to finalize UID copy: {exc}") from exc

    def abandon_pending_uid(self, *, pk: str, uidvalidity: int, gmail_uid: int) -> None:
        sk = self.uid_sk(uidvalidity=uidvalidity, gmail_uid=gmail_uid)
        try:
            self._client.delete_item(
                TableName=self.table_name,
                Key=self._key(pk=pk, sk=sk),
            )
        except Exception as exc:
            raise DynamoStateError(f"Failed to abandon pending UID: {exc}") from exc

    def record_failure(
        self,
        *,
        pk: str,
        uidvalidity: int,
        gmail_uid: int,
        error_message: str,
        ttl_days: int,
    ) -> None:
        sk = self.fail_sk(uidvalidity=uidvalidity, gmail_uid=gmail_uid)
        now = _now_epoch()
        ttl = now + (ttl_days * 86400)

        retry_count = 0
        try:
            existing = self._client.get_item(
                TableName=self.table_name,
                Key=self._key(pk=pk, sk=sk),
                ConsistentRead=True,
            )
            existing_item = existing.get("Item", {}) if isinstance(existing, dict) else {}
            retry_count = (_get_n(existing_item, "retry_count") or 0) + 1
            self._client.put_item(
                TableName=self.table_name,
                Item={
                    "PK": _s(pk),
                    "SK": _s(sk),
                    "last_error": _s(error_message[:1024]),
                    "retry_count": _n(retry_count),
                    "updated_at": _n(now),
                    "ttl": _n(ttl),
                },
            )
        except Exception as exc:
            raise DynamoStateError(f"Failed to record failure: {exc}") from exc

    def payload_already_copied(
        self,
        *,
        pk: str,
        message_id_header: str | None,
        rfc822_sha256: str,
    ) -> bool:
        for item in self._query_uid_items(pk=pk):
            status = _get_s(item, "status") or ""
            if status != "DONE":
                continue
            existing_sha = _get_s(item, "rfc822_sha256")
            if existing_sha and existing_sha == rfc822_sha256:
                return True
            if message_id_header:
                existing_mid = _get_s(item, "message_id_header")
                if existing_mid and existing_mid == message_id_header:
                    return True
        return False

    def _query_uid_items(self, *, pk: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        last_key: dict[str, Any] | None = None
        while True:
            args: dict[str, Any] = {
                "TableName": self.table_name,
                "KeyConditionExpression": "#pk = :pk AND begins_with(#sk, :prefix)",
                "ExpressionAttributeNames": {
                    "#pk": "PK",
                    "#sk": "SK",
                },
                "ExpressionAttributeValues": {
                    ":pk": _s(pk),
                    ":prefix": _s("UID#"),
                },
                "ConsistentRead": True,
            }
            if last_key:
                args["ExclusiveStartKey"] = last_key
            try:
                response = self._client.query(**args)
            except Exception as exc:
                raise DynamoStateError(f"Failed to query UID items: {exc}") from exc
            page = response.get("Items", []) if isinstance(response, dict) else []
            for item in page:
                if isinstance(item, dict):
                    items.append(item)
            last_key = response.get("LastEvaluatedKey") if isinstance(response, dict) else None
            if not last_key:
                break
        return items

