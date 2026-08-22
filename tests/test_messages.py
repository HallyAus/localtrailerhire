"""Tests for message reading + awaiting-reply heuristic.

Shapes verified live: messages/query?transactionId=<id>&include=sender returns
data[].attributes {content, createdAt, deleted} and
relationships.sender.data.id.uuid.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from lth_api import SharetribeFlexAPI


def _msg(
    mid: str,
    sender_id: str,
    *,
    content: str = "hello",
    created: str = "2026-06-21T05:19:04.767Z",
    deleted: bool = False,
) -> dict[str, Any]:
    return {
        "id": {"uuid": mid},
        "type": "message",
        "attributes": {"content": content, "createdAt": created, "deleted": deleted},
        "relationships": {"sender": {"data": {"id": {"uuid": sender_id}}}},
    }


# --- pure helpers ------------------------------------------------------------


def test_parse_messages_extracts_sender_and_fields():
    payload = {"data": [_msg("m1", "U_cust", content="hi")]}
    msgs = SharetribeFlexAPI.parse_messages(payload)
    assert len(msgs) == 1
    m = msgs[0]
    assert m["id"] == "m1"
    assert m["content"] == "hi"
    assert m["sender_id"] == "U_cust"
    assert m["created_at"] == "2026-06-21T05:19:04.767Z"
    assert m["deleted"] is False


def test_latest_message_picks_most_recent_non_deleted():
    msgs = SharetribeFlexAPI.parse_messages(
        {
            "data": [
                _msg("m1", "U_cust", created="2026-06-20T00:00:00.000Z"),
                _msg("m3", "U_prov", created="2026-06-22T00:00:00.000Z", deleted=True),
                _msg("m2", "U_prov", created="2026-06-21T00:00:00.000Z"),
            ]
        }
    )
    latest = SharetribeFlexAPI.latest_message(msgs)
    assert latest["sender_id"] == "U_prov"
    assert latest["created_at"] == "2026-06-21T00:00:00.000Z"


def test_awaiting_reply_true_when_customer_messaged_last():
    msgs = SharetribeFlexAPI.parse_messages(
        {
            "data": [
                _msg("m1", "U_prov", created="2026-06-20T00:00:00.000Z"),
                _msg("m2", "U_cust", created="2026-06-21T00:00:00.000Z"),
            ]
        }
    )
    assert SharetribeFlexAPI.awaiting_reply(msgs, provider_id="U_prov") is True


def test_awaiting_reply_false_when_provider_messaged_last():
    msgs = SharetribeFlexAPI.parse_messages(
        {
            "data": [
                _msg("m1", "U_cust", created="2026-06-20T00:00:00.000Z"),
                _msg("m2", "U_prov", created="2026-06-21T00:00:00.000Z"),
            ]
        }
    )
    assert SharetribeFlexAPI.awaiting_reply(msgs, provider_id="U_prov") is False


def test_awaiting_reply_false_when_no_messages():
    assert SharetribeFlexAPI.awaiting_reply([], provider_id="U_prov") is False


# --- get_messages (mocked session) -------------------------------------------


class _Resp:
    def __init__(self, body: Any, status: int = 200) -> None:
        self.status = status
        self._body = body
        self.headers = {"Content-Type": "application/json"}

    async def __aenter__(self) -> _Resp:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def text(self) -> str:
        return "{}"

    async def json(self) -> Any:
        return self._body


class _Session:
    def __init__(self, responses: list[_Resp]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Resp:
        self.calls.append((url, kwargs.get("params")))
        return self._responses.pop(0)


def _api(responses: list[_Resp]) -> SharetribeFlexAPI:
    api = SharetribeFlexAPI(session=_Session(responses), client_id="cid")
    api._access_token = "tok"
    api._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return api


@pytest.mark.asyncio
async def test_get_messages_queries_transaction_and_parses():
    page = {
        "data": [_msg("m1", "U_cust"), _msg("m2", "U_prov")],
        "meta": {"totalItems": 2, "totalPages": 1, "page": 1, "perPage": 100},
    }
    api = _api([_Resp(page)])
    msgs = await api.get_messages("TXN1")
    assert len(msgs) == 2
    params = [p for _u, p in api._session.calls if p and "transactionId" in p]
    assert params and params[0]["transactionId"] == "TXN1"
    assert params[0].get("include") == "sender"


@pytest.mark.asyncio
async def test_incremental_messages_stop_at_known_newest_first_boundary():
    page = {
        "data": [
            _msg("new-2", "U_cust"),
            _msg("new-1", "U_prov"),
            _msg("known", "U_cust"),
            _msg("old", "U_prov"),
        ]
    }
    api = _api([_Resp(page)])
    messages, complete = await api.get_messages_incremental("TXN1", frozenset({"known"}))
    assert complete is True
    assert [message["id"] for message in messages] == ["new-2", "new-1"]
