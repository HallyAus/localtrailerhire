"""Retry/backoff tests for SharetribeFlexAPI request helpers.

Covers the documented contract that 429 AND 5xx (502/503/504) are retried with
backoff honouring ``Retry-After`` (see SKILL.md / README). Uses a scripted fake
aiohttp session so no network or real sleeping happens (``Retry-After: 0``).
"""

from __future__ import annotations

from typing import Any

import pytest

from lth_api import APIError, SharetribeFlexAPI


class _FakeResponse:
    """Minimal stand-in for an aiohttp response usable as an async ctx manager."""

    def __init__(
        self,
        status: int,
        *,
        json_body: Any = None,
        retry_after: str | None = None,
        content_type: str = "application/json",
    ) -> None:
        self.status = status
        self._json = {} if json_body is None else json_body
        self.headers: dict[str, str] = {"Content-Type": content_type}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def text(self) -> str:
        return "error body"

    async def json(self) -> Any:
        return self._json


class _FakeSession:
    """Pops scripted responses for each request()/post() call."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.request_count = 0

    def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.request_count += 1
        return self._responses.pop(0)

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.request_count += 1
        return self._responses.pop(0)


def _make_api(session: _FakeSession) -> SharetribeFlexAPI:
    return SharetribeFlexAPI(session=session, client_id="cid")


@pytest.mark.asyncio
async def test_request_retries_503_then_succeeds():
    session = _FakeSession(
        [
            _FakeResponse(503, retry_after="0"),
            _FakeResponse(200, json_body={"data": []}),
        ]
    )
    api = _make_api(session)
    result, meta = await api._request_with_retry(
        "GET", "http://x", headers={}, retry_auth=False
    )
    assert result == {"data": []}
    assert meta["status_code"] == 200
    assert session.request_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_request_retries_5xx(status: int):
    session = _FakeSession(
        [
            _FakeResponse(status, retry_after="0"),
            _FakeResponse(200, json_body={"ok": True}),
        ]
    )
    api = _make_api(session)
    result, _meta = await api._request_with_retry(
        "GET", "http://x", headers={}, retry_auth=False
    )
    assert result == {"ok": True}
    assert session.request_count == 2


@pytest.mark.asyncio
async def test_request_503_exhausts_budget_raises():
    # MAX_RATE_LIMIT_RETRIES = 3 -> 1 initial + 3 retries = 4 attempts then raise.
    session = _FakeSession([_FakeResponse(503, retry_after="0") for _ in range(10)])
    api = _make_api(session)
    with pytest.raises(APIError):
        await api._request_with_retry(
            "GET", "http://x", headers={}, retry_auth=False
        )
    assert session.request_count == 4


@pytest.mark.asyncio
async def test_send_message_retries_503_then_succeeds():
    session = _FakeSession(
        [
            _FakeResponse(503, retry_after="0"),
            _FakeResponse(200, content_type="application/transit+json"),
        ]
    )
    api = _make_api(session)
    result = await api._send_message_with_retry(
        headers={}, payload=["^ ", "~:content", "hi"], retry_auth=False
    )
    assert result["success"] is True
    assert session.request_count == 2


@pytest.mark.asyncio
async def test_transition_retries_503_then_succeeds():
    session = _FakeSession(
        [
            _FakeResponse(503, retry_after="0"),
            _FakeResponse(200),
        ]
    )
    api = _make_api(session)
    result = await api._post_transition_with_retry(
        body={"id": "x", "transition": "transition/accept", "params": {}},
        headers={},
        retry_auth=False,
    )
    assert result["success"] is True
    assert session.request_count == 2
