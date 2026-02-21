from __future__ import annotations

from copy import deepcopy
from typing import Any

from src.dynamodb_state import DynamoStateStore


class FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeDynamoClient:
    def __init__(self) -> None:
        self._items: dict[tuple[str, str], dict[str, Any]] = {}

    def describe_table(self, **_: Any) -> dict[str, Any]:
        return {"Table": {"TableStatus": "ACTIVE"}}

    def get_item(self, *, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        key = (Key["PK"]["S"], Key["SK"]["S"])
        item = self._items.get(key)
        if item is None:
            return {}
        return {"Item": deepcopy(item)}

    def put_item(
        self,
        *,
        Item: dict[str, Any],
        ConditionExpression: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        key = (Item["PK"]["S"], Item["SK"]["S"])
        if ConditionExpression == "attribute_not_exists(SK)" and key in self._items:
            raise FakeClientError("ConditionalCheckFailedException")
        self._items[key] = deepcopy(Item)
        return {}

    def delete_item(self, *, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        key = (Key["PK"]["S"], Key["SK"]["S"])
        self._items.pop(key, None)
        return {}

    def query(
        self, *, ExpressionAttributeValues: dict[str, Any], **_: Any
    ) -> dict[str, Any]:
        pk = ExpressionAttributeValues[":pk"]["S"]
        prefix = ExpressionAttributeValues[":prefix"]["S"]
        results = []
        for (item_pk, item_sk), item in sorted(self._items.items()):
            if item_pk == pk and item_sk.startswith(prefix):
                results.append(deepcopy(item))
        return {"Items": results}


def test_claim_and_finalize_uid_idempotency() -> None:
    client = FakeDynamoClient()
    store = DynamoStateStore(table_name="t", region_name="us-east-1", client=client)
    pk = store.route_pk(
        gmail_email="gmail@example.com",
        outlook_email="outlook@example.com",
        folder="Inbox/Gmail-1",
    )

    first_claim = store.claim_uid_copy(pk=pk, uidvalidity=1, gmail_uid=123)
    second_claim = store.claim_uid_copy(pk=pk, uidvalidity=1, gmail_uid=123)
    assert first_claim is True
    assert second_claim is False

    store.finalize_uid_copy(
        pk=pk,
        uidvalidity=1,
        gmail_uid=123,
        message_id_header="<msg-123@example.com>",
        rfc822_sha256="abc123",
        ttl_days=10,
    )
    assert store.payload_already_copied(
        pk=pk,
        message_id_header="<msg-123@example.com>",
        rfc822_sha256="not-match",
    )
    assert store.payload_already_copied(
        pk=pk,
        message_id_header=None,
        rfc822_sha256="abc123",
    )


def test_record_failure_increments_retry_count() -> None:
    client = FakeDynamoClient()
    store = DynamoStateStore(table_name="t", region_name="us-east-1", client=client)
    pk = store.route_pk(
        gmail_email="gmail@example.com",
        outlook_email="outlook@example.com",
        folder="Inbox/Gmail-1",
    )
    store.record_failure(
        pk=pk,
        uidvalidity=1,
        gmail_uid=10,
        error_message="first",
        ttl_days=7,
    )
    store.record_failure(
        pk=pk,
        uidvalidity=1,
        gmail_uid=10,
        error_message="second",
        ttl_days=7,
    )

    fail_item = client.get_item(
        Key={"PK": {"S": pk}, "SK": {"S": "FAIL#1#10"}},
        TableName="t",
    )["Item"]
    assert fail_item["retry_count"]["N"] == "2"
    assert fail_item["last_error"]["S"] == "second"
