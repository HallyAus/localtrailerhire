"""Unit tests for the SharetribeFlexAPI.leave_review fallback logic."""

from __future__ import annotations

from typing import Any

import pytest

from lth_api import APIError, SharetribeFlexAPI


class _FakeAPI:
    """Stand-in that records calls to transition_transaction and replays scripted results."""

    def __init__(self, scripted: list[Any]) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    async def transition_transaction(
        self,
        transaction_id: str,
        transition: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {"transaction_id": transaction_id, "transition": transition, "params": params}
        )
        outcome = self._scripted.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def _run_leave_review(fake: _FakeAPI, **kwargs: Any) -> dict[str, Any]:
    """Bind the real leave_review method to the fake and invoke it."""
    return await SharetribeFlexAPI.leave_review(
        fake,  # type: ignore[arg-type]
        **kwargs,
    )


@pytest.mark.asyncio
async def test_leave_review_uses_review_1_first_on_success():
    fake = _FakeAPI([{"success": True, "status_code": 200}])
    result = await _run_leave_review(
        fake,
        transaction_id="abc",
        rating=5,
        content="Great hirer!",
    )

    assert result["success"] is True
    assert result["transition"] == "transition/review-1-by-provider"
    assert len(fake.calls) == 1
    assert fake.calls[0]["transition"] == "transition/review-1-by-provider"
    assert fake.calls[0]["params"] == {"reviewRating": 5, "reviewContent": "Great hirer!"}


@pytest.mark.asyncio
async def test_leave_review_falls_back_to_review_2_when_review_1_rejected():
    fake = _FakeAPI(
        [
            APIError("review-1 rejected (status 409)"),
            {"success": True, "status_code": 200},
        ]
    )
    result = await _run_leave_review(
        fake,
        transaction_id="abc",
        rating=4,
        content="Solid customer.",
    )

    assert result["success"] is True
    assert result["transition"] == "transition/review-2-by-provider"
    assert [c["transition"] for c in fake.calls] == [
        "transition/review-1-by-provider",
        "transition/review-2-by-provider",
    ]


@pytest.mark.asyncio
async def test_leave_review_raises_when_both_transitions_fail():
    fake = _FakeAPI(
        [APIError("review-1 fail"), APIError("review-2 fail")]
    )
    with pytest.raises(APIError, match="review-2 fail"):
        await _run_leave_review(
            fake, transaction_id="abc", rating=5, content="hi"
        )
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_leave_review_honours_explicit_transition():
    fake = _FakeAPI([{"success": True, "status_code": 200}])
    await _run_leave_review(
        fake,
        transaction_id="abc",
        rating=5,
        content="hi",
        transition="transition/review-2-by-provider",
    )
    assert [c["transition"] for c in fake.calls] == [
        "transition/review-2-by-provider"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_rating", [0, 6, -1, 100])
async def test_leave_review_rejects_out_of_range_rating(bad_rating: int):
    fake = _FakeAPI([])
    with pytest.raises(APIError, match="rating"):
        await _run_leave_review(
            fake, transaction_id="abc", rating=bad_rating, content="hi"
        )
    assert fake.calls == []


@pytest.mark.asyncio
async def test_leave_review_rejects_empty_content():
    fake = _FakeAPI([])
    with pytest.raises(APIError, match="content"):
        await _run_leave_review(
            fake, transaction_id="abc", rating=5, content="   "
        )
    assert fake.calls == []
