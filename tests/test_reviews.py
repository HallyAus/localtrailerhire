"""Tests for provider reviews fetching + aggregation.

Payload shapes verified against the live Sharetribe Marketplace API
(reviews/query?subjectId=<uid> -> type=ofProvider, state=public).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from lth_api import SharetribeFlexAPI


def _review(
    rating: int,
    *,
    rtype: str = "ofProvider",
    state: str = "public",
    deleted: bool = False,
    content: str = "ok",
    created: str = "2026-06-10T19:41:54.462Z",
) -> dict[str, Any]:
    return {
        "id": {"uuid": f"rev-{rating}-{state}-{rtype}"},
        "type": "review",
        "attributes": {
            "type": rtype,
            "state": state,
            "deleted": deleted,
            "rating": rating,
            "content": content,
            "createdAt": created,
        },
        "relationships": {
            "author": {"data": {"id": {"uuid": "U-author"}}},
            "subject": {"data": {"id": {"uuid": "U-subject"}}},
        },
    }


# --- pure helpers ------------------------------------------------------------


def test_parse_reviews_extracts_fields():
    reviews = SharetribeFlexAPI.parse_reviews({"data": [_review(5, content="Great")]})
    assert len(reviews) == 1
    r = reviews[0]
    assert r["id"] == "rev-5-public-ofProvider"
    assert r["rating"] == 5
    assert r["content"] == "Great"
    assert r["type"] == "ofProvider"
    assert r["state"] == "public"
    assert r["created_at"] == "2026-06-10T19:41:54.462Z"
    assert r["author_id"] == "U-author"
    assert r["subject_id"] == "U-subject"


def test_average_rating_mean():
    reviews = SharetribeFlexAPI.parse_reviews({"data": [_review(5), _review(4), _review(3)]})
    assert SharetribeFlexAPI.average_rating(reviews) == 4.0


def test_average_rating_excludes_deleted_nonpublic_and_customer():
    reviews = SharetribeFlexAPI.parse_reviews(
        {
            "data": [
                _review(5),
                _review(1, deleted=True),
                _review(1, state="pending"),
                _review(1, rtype="ofCustomer"),
            ]
        }
    )
    assert SharetribeFlexAPI.average_rating(reviews) == 5.0


def test_average_rating_empty_is_none():
    assert SharetribeFlexAPI.average_rating([]) is None


# --- get_reviews / get_current_user_id (mocked session) ----------------------


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
    # Pre-seed a valid token so _ensure_valid_token does no network.
    api._access_token = "tok"
    api._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return api


@pytest.mark.asyncio
async def test_get_current_user_id_caches():
    cu = {"data": {"id": {"uuid": "U1"}, "attributes": {"profile": {"displayName": "Daniel H"}}}}
    api = _api([_Resp(cu)])
    uid = await api.get_current_user_id()
    assert uid == "U1"
    # cached: second call makes no further request
    uid2 = await api.get_current_user_id()
    assert uid2 == "U1"
    assert len(api._session.calls) == 1


@pytest.mark.asyncio
async def test_get_reviews_queries_subject_id_and_parses():
    cu = {"data": {"id": {"uuid": "U1"}, "attributes": {}}}
    page = {
        "data": [_review(5), _review(4)],
        "meta": {"totalItems": 2, "totalPages": 1, "page": 1, "perPage": 100},
    }
    api = _api([_Resp(cu), _Resp(page)])
    reviews = await api.get_reviews()
    assert len(reviews) == 2
    assert SharetribeFlexAPI.average_rating(reviews) == 4.5
    # the reviews request carried subjectId=U1
    review_calls = [
        params for url, params in api._session.calls if params and "subjectId" in params
    ]
    assert review_calls and review_calls[0]["subjectId"] == "U1"
