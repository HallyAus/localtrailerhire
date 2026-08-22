"""Tests for current-user profile + performance stats parsing.

Shape verified live: current_user/show → data.attributes.profile.privateData
holds bookingStats-<YYYY> and bookingStats-<YYYY-MM> objects with acceptanceRate,
responseRate, numBookings, numHires, missedEarnings, etc.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from lth_api import SharetribeFlexAPI


def _current_user_payload() -> dict[str, Any]:
    return {
        "data": {
            "id": {"uuid": "U1"},
            "type": "currentUser",
            "attributes": {
                "stripePayoutsEnabled": True,
                "stripeChargesEnabled": False,
                "stripeConnected": True,
                "profile": {
                    "displayName": "Daniel H",
                    "privateData": {
                        "bookingStats-2025": {
                            "acceptanceRate": 90,
                            "responseRate": 95,
                            "numBookings": 50,
                            "numHires": 40,
                            "missedEarnings": 1200,
                        },
                        "bookingStats-2026": {
                            "acceptanceRate": 98,
                            "responseRate": 100,
                            "numBookings": 10,
                            "numHires": 8,
                            "numTransactions": 12,
                            "numBookingRequests": 11,
                            "numAcceptedBookings": 9,
                            "numDeclinedBookings": 1,
                            "numExpiredBookings": 1,
                            "numCancelledBookings": 2,
                            "numAbortedBookings": 0,
                            "missedEarnings": 200,
                            "missedEarningsDueToDeclinedBookings": 100,
                            "missedEarningsDueToExpiredBookings": 75,
                            "missedEarningsDueToAbortedBookings": 25,
                            "updatedAt": "2026-06-30T00:00:00Z",
                        },
                        "bookingStats-2026-06": {  # monthly — must be ignored
                            "acceptanceRate": 50,
                            "responseRate": 50,
                        },
                    },
                },
            },
        }
    }


def test_parse_current_user_basic_fields():
    p = SharetribeFlexAPI.parse_current_user(_current_user_payload())
    assert p["id"] == "U1"
    assert p["display_name"] == "Daniel H"
    assert p["payouts_enabled"] is True
    assert p["charges_enabled"] is False


def test_parse_current_user_uses_latest_annual_stats():
    p = SharetribeFlexAPI.parse_current_user(_current_user_payload())
    stats = p["stats"]
    assert stats["year"] == "2026"  # latest annual, not the monthly bucket
    assert stats["acceptance_rate"] == 98
    assert stats["response_rate"] == 100
    assert stats["num_bookings"] == 10
    assert stats["num_hires"] == 8
    assert stats["num_transactions"] == 12
    assert stats["num_booking_requests"] == 11
    assert stats["num_accepted_bookings"] == 9
    assert stats["num_declined_bookings"] == 1
    assert stats["num_expired_bookings"] == 1
    assert stats["num_cancelled_bookings"] == 2
    assert stats["num_aborted_bookings"] == 0
    assert stats["missed_earnings"] == 200
    assert stats["missed_earnings_declined"] == 100
    assert stats["missed_earnings_expired"] == 75
    assert stats["missed_earnings_aborted"] == 25
    assert stats["updated_at"] == "2026-06-30T00:00:00Z"


def test_parse_current_user_empty_when_no_stats():
    p = SharetribeFlexAPI.parse_current_user(
        {"data": {"id": {"uuid": "U2"}, "attributes": {"profile": {}}}}
    )
    assert p["id"] == "U2"
    assert p["stats"] == {}


# --- get_current_user (mocked) ----------------------------------------------


class _Resp:
    def __init__(self, body: Any) -> None:
        self.status = 200
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
        self.count = 0

    def request(self, method: str, url: str, **kwargs: Any) -> _Resp:
        self.count += 1
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_get_current_user_fetches_and_caches_id():
    api = SharetribeFlexAPI(session=_Session([_Resp(_current_user_payload())]), client_id="c")
    api._access_token = "tok"
    api._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    profile = await api.get_current_user()
    assert profile["display_name"] == "Daniel H"
    # id cached → get_current_user_id makes no further request
    uid = await api.get_current_user_id()
    assert uid == "U1"
    assert api._session.count == 1
