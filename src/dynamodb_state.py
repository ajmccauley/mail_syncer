from __future__ import annotations

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
        return (
            f"ROUTE#{gmail_email}"
            f"#DEST#{outlook_email}"
            f"#FOLDER#{folder}"
        )

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
        """
        Placeholder for watermark retrieval.

        Full watermark + UID idempotency schema operations are implemented in a
        later batch after runtime safety and routing are fully wired.
        """
        raise NotImplementedError("Watermark retrieval not implemented yet")

