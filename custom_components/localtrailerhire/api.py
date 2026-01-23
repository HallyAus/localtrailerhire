"""API client for Sharetribe Flex (LocalTrailerHire)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

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
        # Diagnostics data for debugging
        self._last_diagnostics: dict[str, Any] = {}

    @property
    def refresh_token(self) -> str | None:
        """Return the current refresh token."""
        return self._refresh_token

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Return last diagnostics data for debugging."""
        return self._last_diagnostics

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        retry_auth: bool = True,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Make a request with automatic retry on 401.

        Returns: (response_json, response_meta)
        response_meta contains status_code, content_type, headers for diagnostics
        """
        try:
            async with self._session.request(method, url, **kwargs) as response:
                content_type = response.headers.get("Content-Type", "unknown")
                status_code = response.status

                response_meta = {
                    "status_code": status_code,
                    "content_type": content_type,
                }

                _LOGGER.debug(
                    "API Response: status=%d, content_type=%s, url=%s",
                    status_code,
                    content_type,
                    url,
                )

                if status_code == 401 and retry_auth:
                    _LOGGER.debug("Got 401, attempting token refresh")
                    await self._refresh_access_token(force=True)
                    # Update authorization header
                    if "headers" in kwargs:
                        kwargs["headers"]["Authorization"] = f"Bearer {self._access_token}"
                    return await self._request_with_retry(
                        method, url, retry_auth=False, **kwargs
                    )

                if status_code == 429:
                    # Rate limited, wait and retry
                    retry_after = int(response.headers.get("Retry-After", 60))
                    _LOGGER.warning("Rate limited, waiting %d seconds", retry_after)
                    await asyncio.sleep(retry_after)
                    return await self._request_with_retry(
                        method, url, retry_auth=retry_auth, **kwargs
                    )

                if status_code >= 400:
                    text = await response.text()
                    # Log error details (sanitized - no tokens)
                    _LOGGER.error(
                        "API request failed: status=%d, content_type=%s, url=%s, "
                        "response_preview=%s",
                        status_code,
                        content_type,
                        url,
                        text[:500] if text else "(empty)",
                    )
                    raise APIError(f"Request failed with status {status_code}")

                # Verify we got JSON response
                if "application/json" not in content_type.lower():
                    text = await response.text()
                    _LOGGER.error(
                        "Unexpected content type (expected JSON): content_type=%s, "
                        "response_preview=%s",
                        content_type,
                        text[:200] if text else "(empty)",
                    )
                    raise APIError(f"Expected JSON but got {content_type}")

                result = await response.json()
                return result, response_meta

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
                content_type = response.headers.get("Content-Type", "unknown")
                _LOGGER.debug(
                    "Auth response: status=%d, content_type=%s",
                    response.status,
                    content_type,
                )

                if response.status != 200:
                    text = await response.text()
                    _LOGGER.error(
                        "Password grant failed: status=%d, response=%s",
                        response.status,
                        text[:200] if text else "(empty)",
                    )
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
                content_type = response.headers.get("Content-Type", "unknown")
                _LOGGER.debug(
                    "Token refresh response: status=%d, content_type=%s",
                    response.status,
                    content_type,
                )

                if response.status != 200:
                    text = await response.text()
                    _LOGGER.error(
                        "Token refresh failed: status=%d, response=%s",
                        response.status,
                        text[:200] if text else "(empty)",
                    )
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
        """Fetch all transactions matching the criteria.

        Upcoming bookings are determined SOLELY by booking dates:
            upcoming = booking_end >= now (UTC)

        The last_transitions filter is OPTIONAL:
        - If empty/None: fetch ALL provider transactions (recommended)
        - If provided: only fetch transactions with those last transitions

        Booking dates are the authoritative source for "upcoming" status,
        NOT the transition state.
        """
        await self._ensure_valid_token()

        if last_transitions is None:
            last_transitions = DEFAULT_LAST_TRANSITIONS

        # Log filter status
        if last_transitions:
            _LOGGER.debug(
                "Using transition filter: %s", last_transitions
            )
        else:
            _LOGGER.info(
                "No transition filter - fetching ALL transactions, "
                "will determine upcoming by booking dates only"
            )

        all_transactions: list[dict[str, Any]] = []
        all_included: list[dict[str, Any]] = []
        page = 1

        # Initialize diagnostics
        diagnostics: dict[str, Any] = {
            "request_time": datetime.now(timezone.utc).isoformat(),
            "pages": [],
            "total_transactions_fetched": 0,
            "total_upcoming": 0,
            "total_past": 0,
            "total_unknown_dates": 0,
            "sample_transactions": [],
        }

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

            # Log the request URL (sanitized - no token in URL)
            query_string = urlencode(params)
            _LOGGER.info(
                "Fetching transactions: url=%s?%s",
                TRANSACTIONS_URL,
                query_string,
            )

            result, response_meta = await self._request_with_retry(
                "GET", TRANSACTIONS_URL, headers=headers, params=params
            )

            data = result.get("data", [])
            included = result.get("included", [])
            meta = result.get("meta", {})

            # Extract pagination info
            total_items = meta.get("totalItems", 0)
            total_pages = meta.get("totalPages", 1)
            current_page = meta.get("page", page)

            # Log detailed pagination info
            _LOGGER.info(
                "Transactions response: page=%d/%d, per_page=%d, "
                "transactions_this_page=%d, total_items=%d, content_type=%s",
                current_page,
                total_pages,
                per_page,
                len(data),
                total_items,
                response_meta.get("content_type", "unknown"),
            )

            # Store page diagnostics
            page_diag = {
                "page": current_page,
                "total_pages": total_pages,
                "per_page": per_page,
                "transactions_count": len(data),
                "included_count": len(included),
                "total_items": total_items,
                "status_code": response_meta.get("status_code"),
                "content_type": response_meta.get("content_type"),
            }
            diagnostics["pages"].append(page_diag)

            all_transactions.extend(data)
            all_included.extend(included)

            if page >= total_pages or not data:
                break

            page += 1

        diagnostics["total_transactions_fetched"] = len(all_transactions)

        # Process transactions with detailed logging
        processed = self._process_transactions(
            all_transactions, all_included, diagnostics
        )

        # Store diagnostics for later retrieval
        self._last_diagnostics = diagnostics

        _LOGGER.info(
            "Transaction processing complete: total_fetched=%d, upcoming=%d, "
            "past=%d, unknown_dates=%d",
            diagnostics["total_transactions_fetched"],
            diagnostics["total_upcoming"],
            diagnostics["total_past"],
            diagnostics["total_unknown_dates"],
        )

        return processed

    def _process_transactions(
        self,
        transactions: list[dict[str, Any]],
        included: list[dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Process raw transactions into structured booking data.

        Upcoming = booking_end >= now (UTC)
        If booking dates are missing, keep as "unknown" but include in results.
        """
        # Build lookup maps for included entities
        bookings_map: dict[str, dict] = {}
        customers_map: dict[str, dict] = {}
        listings_map: dict[str, dict] = {}

        _LOGGER.debug(
            "Building entity maps from %d included items",
            len(included),
        )

        for item in included:
            item_type = item.get("type")
            # Handle both {uuid: "..."} and direct string ID formats
            item_id_obj = item.get("id", {})
            if isinstance(item_id_obj, dict):
                item_id = item_id_obj.get("uuid")
            else:
                item_id = item_id_obj

            if not item_id:
                continue

            if item_type == "booking":
                bookings_map[item_id] = item
                _LOGGER.debug(
                    "Found booking entity: id=%s, attrs=%s",
                    item_id,
                    list(item.get("attributes", {}).keys()),
                )
            elif item_type == "user":
                customers_map[item_id] = item
            elif item_type == "listing":
                listings_map[item_id] = item

        _LOGGER.debug(
            "Entity maps: bookings=%d, customers=%d, listings=%d",
            len(bookings_map),
            len(customers_map),
            len(listings_map),
        )

        processed: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        sample_count = 0

        for txn in transactions:
            try:
                booking_data, debug_info = self._extract_booking_data(
                    txn, bookings_map, customers_map, listings_map, now
                )

                # Log first 3 transactions for debugging
                if sample_count < 3:
                    diagnostics["sample_transactions"].append(debug_info)
                    _LOGGER.info(
                        "Sample transaction [%d]: id=%s, last_transition=%s, "
                        "booking_start=%s, booking_end=%s, is_upcoming=%s, reason=%s",
                        sample_count,
                        debug_info.get("transaction_id", "unknown"),
                        debug_info.get("last_transition", "unknown"),
                        debug_info.get("booking_start", "missing"),
                        debug_info.get("booking_end", "missing"),
                        debug_info.get("is_upcoming", "unknown"),
                        debug_info.get("upcoming_reason", "n/a"),
                    )
                    sample_count += 1

                if booking_data:
                    is_upcoming = debug_info.get("is_upcoming")

                    if is_upcoming is True:
                        diagnostics["total_upcoming"] += 1
                        processed.append(booking_data)
                    elif is_upcoming is False:
                        diagnostics["total_past"] += 1
                    else:  # is_upcoming is None/unknown
                        diagnostics["total_unknown_dates"] += 1
                        # Include transactions with unknown dates
                        booking_data["_dates_unknown"] = True
                        processed.append(booking_data)

            except Exception as err:
                _LOGGER.warning(
                    "Error processing transaction %s: %s",
                    txn.get("id", {}).get("uuid", "unknown"),
                    err,
                )
                continue

        # Sort by booking start date (unknown dates go to end)
        processed.sort(
            key=lambda x: x.get("booking_start") or "9999-12-31T00:00:00Z"
        )

        return processed

    def _extract_booking_data(
        self,
        txn: dict[str, Any],
        bookings_map: dict[str, dict],
        customers_map: dict[str, dict],
        listings_map: dict[str, dict],
        now: datetime,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Extract structured booking data from a transaction.

        Returns: (booking_data, debug_info)
        debug_info contains diagnostic information for logging.
        """
        # Extract transaction ID (handle both formats)
        txn_id_obj = txn.get("id", {})
        if isinstance(txn_id_obj, dict):
            txn_id = txn_id_obj.get("uuid")
        else:
            txn_id = txn_id_obj

        debug_info: dict[str, Any] = {
            "transaction_id": txn_id,
            "is_upcoming": None,
            "upcoming_reason": None,
        }

        if not txn_id:
            debug_info["upcoming_reason"] = "no_transaction_id"
            return None, debug_info

        attrs = txn.get("attributes", {})
        relationships = txn.get("relationships", {})

        debug_info["last_transition"] = attrs.get("lastTransition")
        debug_info["state"] = attrs.get("state")

        # Get booking details from relationships
        booking_ref = relationships.get("booking", {}).get("data", {})
        if isinstance(booking_ref, dict):
            booking_id_obj = booking_ref.get("id", {})
            if isinstance(booking_id_obj, dict):
                booking_id = booking_id_obj.get("uuid")
            else:
                booking_id = booking_id_obj
        else:
            booking_id = None

        booking = bookings_map.get(booking_id, {}) if booking_id else {}
        booking_attrs = booking.get("attributes", {})

        # Extract booking start/end
        booking_start = booking_attrs.get("start")
        booking_end = booking_attrs.get("end")

        debug_info["booking_id"] = booking_id
        debug_info["booking_start"] = booking_start
        debug_info["booking_end"] = booking_end
        debug_info["booking_found_in_included"] = bool(booking)

        # Determine if upcoming
        is_upcoming: bool | None = None
        if booking_end:
            try:
                # Parse booking end time
                end_str = booking_end
                if isinstance(end_str, str):
                    # Handle various ISO formats
                    if end_str.endswith("Z"):
                        end_str = end_str[:-1] + "+00:00"
                    end_dt = datetime.fromisoformat(end_str)

                    # Ensure timezone aware
                    if end_dt.tzinfo is None:
                        end_dt = end_dt.replace(tzinfo=timezone.utc)

                    is_upcoming = end_dt >= now
                    debug_info["is_upcoming"] = is_upcoming
                    debug_info["upcoming_reason"] = (
                        f"booking_end ({end_dt.isoformat()}) >= now ({now.isoformat()})"
                        if is_upcoming
                        else f"booking_end ({end_dt.isoformat()}) < now ({now.isoformat()})"
                    )
            except (ValueError, TypeError) as err:
                _LOGGER.warning(
                    "Failed to parse booking_end for transaction %s: %s",
                    txn_id, err
                )
                debug_info["upcoming_reason"] = f"parse_error: {err}"
        else:
            debug_info["upcoming_reason"] = "booking_end_missing"
            # Keep as unknown (is_upcoming = None)

        # Get customer details
        customer_ref = relationships.get("customer", {}).get("data", {})
        if isinstance(customer_ref, dict):
            customer_id_obj = customer_ref.get("id", {})
            if isinstance(customer_id_obj, dict):
                customer_id = customer_id_obj.get("uuid")
            else:
                customer_id = customer_id_obj
        else:
            customer_id = None

        customer = customers_map.get(customer_id, {}) if customer_id else {}
        customer_attrs = customer.get("attributes", {})
        customer_profile = customer_attrs.get("profile", {})

        # Get listing details
        listing_ref = relationships.get("listing", {}).get("data", {})
        if isinstance(listing_ref, dict):
            listing_id_obj = listing_ref.get("id", {})
            if isinstance(listing_id_obj, dict):
                listing_id = listing_id_obj.get("uuid")
            else:
                listing_id = listing_id_obj
        else:
            listing_id = None

        listing = listings_map.get(listing_id, {}) if listing_id else {}
        listing_attrs = listing.get("attributes", {})

        # Extract protected data for pickup/address info
        protected_data = attrs.get("protectedData", {}) or {}

        # Extract payout and payin totals
        payout_total = attrs.get("payoutTotal", {})
        payin_total = attrs.get("payinTotal", {})

        booking_data = {
            "transaction_id": txn_id,
            "booking_start": booking_start,
            "booking_end": booking_end,
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

        return booking_data, debug_info

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
