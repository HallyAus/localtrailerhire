"""API client for Sharetribe Flex (LocalTrailerHire)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import (
    AUTH_TOKEN_URL,
    DEFAULT_LAST_TRANSITIONS,
    DEFAULT_PER_PAGE,
    TOKEN_REFRESH_BUFFER,
    TRANSACTIONS_URL,
)

_LOGGER = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Authentication failed."""


class APIError(Exception):
    """API request failed."""


class SharetribeFlexAPI:
    """Client for Sharetribe Flex API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        client_id: str,
        username: str | None = None,
        password: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._client_id = client_id
        self._username = username
        self._password = password
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._token_expiry: datetime | None = None
        self._lock = asyncio.Lock()

    @property
    def refresh_token(self) -> str | None:
        """Return the current refresh token."""
        return self._refresh_token

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Make a request with automatic retry on 401."""
        try:
            async with self._session.request(method, url, **kwargs) as response:
                if response.status == 401 and retry_auth:
                    _LOGGER.debug("Got 401, attempting token refresh")
                    await self._refresh_access_token(force=True)
                    # Update authorization header
                    if "headers" in kwargs:
                        kwargs["headers"]["Authorization"] = f"Bearer {self._access_token}"
                    return await self._request_with_retry(
                        method, url, retry_auth=False, **kwargs
                    )

                if response.status == 429:
                    # Rate limited, wait and retry
                    retry_after = int(response.headers.get("Retry-After", 60))
                    _LOGGER.warning("Rate limited, waiting %d seconds", retry_after)
                    await asyncio.sleep(retry_after)
                    return await self._request_with_retry(
                        method, url, retry_auth=retry_auth, **kwargs
                    )

                if response.status >= 400:
                    text = await response.text()
                    # Sanitize error message (don't log tokens)
                    _LOGGER.error(
                        "API request failed: status=%d, url=%s",
                        response.status,
                        url,
                    )
                    raise APIError(f"Request failed with status {response.status}")

                return await response.json()

        except aiohttp.ClientError as err:
            _LOGGER.error("Network error during API request: %s", type(err).__name__)
            raise APIError(f"Network error: {type(err).__name__}") from err

    async def authenticate(self) -> None:
        """Authenticate with the API."""
        async with self._lock:
            await self._authenticate_internal()

    async def _authenticate_internal(self) -> None:
        """Internal authentication logic (must hold lock)."""
        if self._refresh_token:
            try:
                await self._do_refresh_token()
                return
            except AuthenticationError:
                _LOGGER.warning("Refresh token failed, falling back to password grant")

        if self._username and self._password:
            await self._do_password_grant()
        else:
            raise AuthenticationError("No valid credentials available")

    async def _do_password_grant(self) -> None:
        """Authenticate using password grant."""
        _LOGGER.debug("Authenticating with password grant")

        data = {
            "grant_type": "password",
            "client_id": self._client_id,
            "username": self._username,
            "password": self._password,
            "scope": "user",
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            async with self._session.post(
                AUTH_TOKEN_URL, data=data, headers=headers
            ) as response:
                if response.status != 200:
                    _LOGGER.error("Password grant failed with status %d", response.status)
                    raise AuthenticationError("Password authentication failed")

                result = await response.json()
                self._process_token_response(result)

        except aiohttp.ClientError as err:
            raise AuthenticationError(f"Network error during auth: {err}") from err

    async def _do_refresh_token(self) -> None:
        """Refresh the access token using refresh token."""
        _LOGGER.debug("Refreshing access token")

        data = {
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "refresh_token": self._refresh_token,
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            async with self._session.post(
                AUTH_TOKEN_URL, data=data, headers=headers
            ) as response:
                if response.status != 200:
                    _LOGGER.error("Token refresh failed with status %d", response.status)
                    raise AuthenticationError("Token refresh failed")

                result = await response.json()
                self._process_token_response(result)

        except aiohttp.ClientError as err:
            raise AuthenticationError(f"Network error during refresh: {err}") from err

    def _process_token_response(self, result: dict[str, Any]) -> None:
        """Process token response and store credentials."""
        self._access_token = result.get("access_token")
        self._refresh_token = result.get("refresh_token", self._refresh_token)

        expires_in = result.get("expires_in", 600)
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        _LOGGER.debug("Token obtained, expires in %d seconds", expires_in)

    async def _ensure_valid_token(self) -> None:
        """Ensure we have a valid access token."""
        async with self._lock:
            if self._access_token is None:
                await self._authenticate_internal()
                return

            # Check if token is about to expire
            if self._token_expiry:
                buffer = timedelta(seconds=TOKEN_REFRESH_BUFFER)
                if datetime.now(timezone.utc) + buffer >= self._token_expiry:
                    _LOGGER.debug("Token expiring soon, refreshing")
                    await self._authenticate_internal()

    async def _refresh_access_token(self, force: bool = False) -> None:
        """Refresh the access token."""
        async with self._lock:
            if force or self._access_token is None:
                await self._authenticate_internal()

    async def get_transactions(
        self,
        last_transitions: list[str] | None = None,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> list[dict[str, Any]]:
        """Fetch all transactions matching the criteria."""
        await self._ensure_valid_token()

        if last_transitions is None:
            last_transitions = DEFAULT_LAST_TRANSITIONS

        all_transactions: list[dict[str, Any]] = []
        all_included: list[dict[str, Any]] = []
        page = 1

        while True:
            params = {
                "only": "sale",
                "per_page": str(per_page),
                "page": str(page),
                "include": "booking,customer,listing",
            }

            # Add transitions filter
            if last_transitions:
                params["lastTransitions"] = ",".join(last_transitions)

            headers = {
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
            }

            result = await self._request_with_retry(
                "GET", TRANSACTIONS_URL, headers=headers, params=params
            )

            data = result.get("data", [])
            included = result.get("included", [])

            all_transactions.extend(data)
            all_included.extend(included)

            # Check pagination
            meta = result.get("meta", {})
            total_pages = meta.get("totalPages", 1)

            _LOGGER.debug("Fetched page %d of %d (%d transactions)", page, total_pages, len(data))

            if page >= total_pages or not data:
                break

            page += 1

        return self._process_transactions(all_transactions, all_included)

    def _process_transactions(
        self,
        transactions: list[dict[str, Any]],
        included: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Process raw transactions into structured booking data."""
        # Build lookup maps for included entities
        bookings_map: dict[str, dict] = {}
        customers_map: dict[str, dict] = {}
        listings_map: dict[str, dict] = {}

        for item in included:
            item_type = item.get("type")
            item_id = item.get("id", {}).get("uuid")
            if not item_id:
                continue

            if item_type == "booking":
                bookings_map[item_id] = item
            elif item_type == "user":
                customers_map[item_id] = item
            elif item_type == "listing":
                listings_map[item_id] = item

        processed: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for txn in transactions:
            try:
                booking_data = self._extract_booking_data(
                    txn, bookings_map, customers_map, listings_map
                )
                if booking_data:
                    # Filter for upcoming bookings (end date >= now)
                    end_str = booking_data.get("booking_end")
                    if end_str:
                        end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                        if end_dt >= now:
                            processed.append(booking_data)
            except Exception as err:
                _LOGGER.warning("Error processing transaction: %s", err)
                continue

        # Sort by booking start date
        processed.sort(
            key=lambda x: x.get("booking_start", "9999-12-31T00:00:00Z")
        )

        return processed

    def _extract_booking_data(
        self,
        txn: dict[str, Any],
        bookings_map: dict[str, dict],
        customers_map: dict[str, dict],
        listings_map: dict[str, dict],
    ) -> dict[str, Any] | None:
        """Extract structured booking data from a transaction."""
        txn_id = txn.get("id", {}).get("uuid")
        if not txn_id:
            return None

        attrs = txn.get("attributes", {})
        relationships = txn.get("relationships", {})

        # Get booking details
        booking_ref = relationships.get("booking", {}).get("data", {})
        booking_id = booking_ref.get("id", {}).get("uuid")
        booking = bookings_map.get(booking_id, {}) if booking_id else {}
        booking_attrs = booking.get("attributes", {})

        # Get customer details
        customer_ref = relationships.get("customer", {}).get("data", {})
        customer_id = customer_ref.get("id", {}).get("uuid")
        customer = customers_map.get(customer_id, {}) if customer_id else {}
        customer_attrs = customer.get("attributes", {})
        customer_profile = customer_attrs.get("profile", {})

        # Get listing details
        listing_ref = relationships.get("listing", {}).get("data", {})
        listing_id = listing_ref.get("id", {}).get("uuid")
        listing = listings_map.get(listing_id, {}) if listing_id else {}
        listing_attrs = listing.get("attributes", {})

        # Extract protected data for pickup/address info
        protected_data = attrs.get("protectedData", {})

        # Extract payout and payin totals
        payout_total = attrs.get("payoutTotal", {})
        payin_total = attrs.get("payinTotal", {})

        return {
            "transaction_id": txn_id,
            "booking_start": booking_attrs.get("start"),
            "booking_end": booking_attrs.get("end"),
            "customer_first_name": customer_profile.get("firstName"),
            "customer_last_name": customer_profile.get("lastName"),
            "customer_display_name": customer_profile.get("displayName"),
            "customer_phone": protected_data.get("customerPhoneNumber")
            or protected_data.get("phoneNumber"),
            "pickup_address": protected_data.get("pickupAddress")
            or protected_data.get("address"),
            "pickup_suburb": protected_data.get("suburb"),
            "payout_total_aud": self._format_money(payout_total),
            "payin_total_aud": self._format_money(payin_total),
            "last_transition": attrs.get("lastTransition"),
            "state": booking_attrs.get("state"),
            "last_transitioned_at": attrs.get("lastTransitionedAt"),
            "listing_title": listing_attrs.get("title"),
            "listing_id": listing_id,
        }

    @staticmethod
    def _format_money(money: dict[str, Any] | None) -> float | None:
        """Format money object to decimal amount."""
        if not money:
            return None
        amount = money.get("amount")
        if amount is not None:
            # Amount is in cents
            return amount / 100
        return None


async def validate_credentials(
    session: aiohttp.ClientSession,
    client_id: str,
    username: str | None = None,
    password: str | None = None,
    refresh_token: str | None = None,
) -> tuple[bool, str | None]:
    """Validate credentials and return (success, refresh_token)."""
    api = SharetribeFlexAPI(
        session=session,
        client_id=client_id,
        username=username,
        password=password,
        refresh_token=refresh_token,
    )

    try:
        await api.authenticate()
        return True, api.refresh_token
    except AuthenticationError as err:
        _LOGGER.error("Credential validation failed: %s", err)
        return False, None
