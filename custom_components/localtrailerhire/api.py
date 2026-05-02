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
    MAX_PAGES,
    MESSAGE_SEND_URL,
    OWN_LISTINGS_URL,
    TOKEN_REFRESH_BUFFER,
    TRANSACTIONS_URL,
    TRANSITION_URL,
)
from .util import parse_iso_datetime

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
    def has_access_token(self) -> bool:
        """Return whether an access token is currently held."""
        return self._access_token is not None

    @property
    def token_expiry(self) -> datetime | None:
        """Return the access token expiry timestamp, if known."""
        return self._token_expiry

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
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch all transactions matching the criteria.

        Upcoming bookings are determined SOLELY by booking dates:
            upcoming = booking_end >= now (UTC)

        The last_transitions filter is OPTIONAL:
        - If empty/None: fetch ALL provider transactions (recommended)
        - If provided: only fetch transactions with those last transitions

        Booking dates are the authoritative source for "upcoming" status,
        NOT the transition state.

        Args:
            last_transitions: Optional list of transitions to filter by.
            per_page: Number of results per page.
            include_sensitive: If True, include full licence and unmasked phone.
                              If False, omit licence and mask phone numbers.
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
            _LOGGER.debug(
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
            _LOGGER.debug(
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
            _LOGGER.debug(
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

            # Robust pagination: stop when we get fewer results than requested
            # OR when we hit the safety cap on max pages
            if len(data) < per_page:
                _LOGGER.debug(
                    "Pagination complete: received %d items (less than per_page=%d)",
                    len(data),
                    per_page,
                )
                break

            if page >= MAX_PAGES:
                _LOGGER.warning(
                    "Hit MAX_PAGES safety limit (%d). There may be more transactions.",
                    MAX_PAGES,
                )
                break

            page += 1

        diagnostics["total_transactions_fetched"] = len(all_transactions)

        # Process transactions with detailed logging
        processed = self._process_transactions(
            all_transactions, all_included, diagnostics, include_sensitive
        )

        # Store diagnostics for later retrieval
        self._last_diagnostics = diagnostics

        _LOGGER.debug(
            "Transaction processing complete: total_fetched=%d, upcoming=%d, "
            "past=%d, unknown_dates=%d",
            diagnostics["total_transactions_fetched"],
            diagnostics["total_upcoming"],
            diagnostics["total_past"],
            diagnostics["total_unknown_dates"],
        )

        return processed

    async def send_message(
        self,
        transaction_id: str,
        message: str,
    ) -> dict[str, Any]:
        """Send a message to a transaction using Transit format.

        The Sharetribe Marketplace API requires Transit encoding for messages.
        This matches the exact format used by the web application.

        Args:
            transaction_id: The UUID of the transaction to message.
            message: The message content to send.

        Returns:
            Dict with success status and message_id if available.

        Raises:
            APIError: If the request fails.
            AuthenticationError: If authentication fails.
        """
        # Validate inputs
        if not transaction_id:
            raise APIError("transaction_id is required")
        if not message:
            raise APIError("message is required")

        _LOGGER.debug(
            "SEND_MESSAGE: Starting - transaction_id=%s, message_length=%d chars",
            transaction_id,
            len(message),
        )

        # Ensure we have a valid token
        try:
            await self._ensure_valid_token()
        except AuthenticationError as err:
            _LOGGER.error("Failed to authenticate before sending message: %s", err)
            raise

        if not self._access_token:
            raise AuthenticationError("No access token available")

        # Use Transit format exactly as the web app does
        # Transit array format: ["^ ", "~:transactionId", "~u<uuid>", "~:content", "<message>"]
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/transit+json",
            "Content-Type": "application/transit+json",
        }

        # Build Transit payload as a JSON array (NOT object)
        # "~u" prefix indicates UUID type in Transit
        transit_payload = [
            "^ ",
            "~:transactionId",
            f"~u{transaction_id}",
            "~:content",
            message,
        ]

        _LOGGER.debug(
            "Sending message via Transit API: url=%s",
            MESSAGE_SEND_URL,
        )

        # Send with retry on 401
        result = await self._send_message_with_retry(
            headers=headers,
            payload=transit_payload,
            retry_auth=True,
        )

        return result

    async def _send_message_with_retry(
        self,
        headers: dict[str, str],
        payload: list,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        """Send message request with automatic retry on 401.

        Args:
            headers: Request headers.
            payload: Transit-encoded payload (JSON array).
            retry_auth: Whether to retry on 401.

        Returns:
            Dict with success status.

        Raises:
            APIError: If the request fails.
            AuthenticationError: If authentication fails after retry.
        """
        try:
            async with self._session.post(
                MESSAGE_SEND_URL,
                json=payload,  # aiohttp will JSON-encode the array
                headers=headers,
            ) as response:
                status_code = response.status
                content_type = response.headers.get("Content-Type", "unknown")

                _LOGGER.debug(
                    "Message API response: status=%d, content_type=%s",
                    status_code,
                    content_type,
                )

                # Handle 401 - refresh token and retry once
                if status_code == 401 and retry_auth:
                    _LOGGER.debug("Got 401 on message send, refreshing token")
                    await self._refresh_access_token(force=True)

                    # Update authorization header with new token
                    headers["Authorization"] = f"Bearer {self._access_token}"

                    return await self._send_message_with_retry(
                        headers=headers,
                        payload=payload,
                        retry_auth=False,  # Don't retry again
                    )

                # Handle rate limiting
                if status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    _LOGGER.warning(
                        "Rate limited on message send, waiting %d seconds",
                        retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    return await self._send_message_with_retry(
                        headers=headers,
                        payload=payload,
                        retry_auth=retry_auth,
                    )

                # Get response text for logging (sanitized)
                response_text = await response.text()

                # Handle errors
                if status_code >= 400:
                    # Sanitize response for logging (remove any tokens/secrets)
                    safe_preview = response_text[:500] if response_text else "(empty)"
                    _LOGGER.error(
                        "Message send failed: status=%d, response=%s",
                        status_code,
                        safe_preview,
                    )
                    raise APIError(
                        f"Message send failed with status {status_code}"
                    )

                # Success!
                _LOGGER.debug(
                    "SEND_MESSAGE: SUCCESS - status=%d, transaction_id from payload=%s",
                    status_code,
                    payload[2] if len(payload) > 2 else "unknown",  # ~u<uuid>
                )

                return {
                    "success": True,
                    "status_code": status_code,
                }

        except aiohttp.ClientError as err:
            _LOGGER.error(
                "Network error sending message: %s",
                type(err).__name__,
            )
            raise APIError(f"Network error: {type(err).__name__}") from err

    async def transition_transaction(
        self,
        transaction_id: str,
        transition: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Transition a transaction to a new state (accept, decline, cancel, ...).

        Sharetribe accepts both JSON and Transit payloads on this endpoint;
        we use JSON because the body is plain string fields plus an optional
        params object. Returns ``{"success": True, "status_code": ...}``.
        """
        if not transaction_id:
            raise APIError("transaction_id is required")
        if not transition:
            raise APIError("transition is required")

        await self._ensure_valid_token()
        if not self._access_token:
            raise AuthenticationError("No access token available")

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        body = {
            "id": transaction_id,
            "transition": transition,
            "params": params or {},
        }

        return await self._post_transition_with_retry(
            body=body, headers=headers, retry_auth=True
        )

    async def leave_review(
        self,
        transaction_id: str,
        rating: int,
        content: str,
        transition: str | None = None,
    ) -> dict[str, Any]:
        """Post a provider review on a completed booking.

        Sharetribe's default trailer-hire process exposes two provider-review
        transitions: ``transition/review-1-by-provider`` (provider goes first)
        and ``transition/review-2-by-provider`` (after the customer has
        already reviewed). When ``transition`` is None, ``review-1`` is tried
        first and ``review-2`` is used as a fallback if Sharetribe rejects it
        (typically because the customer reviewed first).

        Returns ``{"success": True, "status_code": ..., "transition": <used>}``.
        """
        if not 1 <= int(rating) <= 5:
            raise APIError("rating must be between 1 and 5")
        if not content or not content.strip():
            raise APIError("review content cannot be empty")

        from .const import (
            TRANSITION_REVIEW_BY_PROVIDER_FIRST,
            TRANSITION_REVIEW_BY_PROVIDER_SECOND,
        )

        params = {
            "reviewRating": int(rating),
            "reviewContent": content.strip(),
        }

        candidates: list[str]
        if transition:
            candidates = [transition]
        else:
            candidates = [
                TRANSITION_REVIEW_BY_PROVIDER_FIRST,
                TRANSITION_REVIEW_BY_PROVIDER_SECOND,
            ]

        last_err: APIError | None = None
        for trans in candidates:
            try:
                result = await self.transition_transaction(
                    transaction_id, trans, params=params
                )
                return {**result, "transition": trans}
            except APIError as err:
                last_err = err
                _LOGGER.debug(
                    "Review transition %s failed (%s); trying next candidate",
                    trans,
                    err,
                )
                continue

        assert last_err is not None  # candidates is non-empty
        raise last_err

    async def _post_transition_with_retry(
        self,
        body: dict[str, Any],
        headers: dict[str, str],
        retry_auth: bool,
    ) -> dict[str, Any]:
        """POST to /transactions/transition with one 401 retry."""
        try:
            async with self._session.post(
                TRANSITION_URL, json=body, headers=headers
            ) as response:
                status_code = response.status

                if status_code == 401 and retry_auth:
                    _LOGGER.debug("Got 401 on transition, refreshing token")
                    await self._refresh_access_token(force=True)
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    return await self._post_transition_with_retry(
                        body=body, headers=headers, retry_auth=False
                    )

                if status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    _LOGGER.warning(
                        "Rate limited on transition, waiting %ds", retry_after
                    )
                    await asyncio.sleep(retry_after)
                    return await self._post_transition_with_retry(
                        body=body, headers=headers, retry_auth=retry_auth
                    )

                if status_code >= 400:
                    text = await response.text()
                    _LOGGER.error(
                        "Transition failed: status=%d, transition=%s, response=%s",
                        status_code,
                        body.get("transition"),
                        text[:500] if text else "(empty)",
                    )
                    raise APIError(
                        f"Transition {body.get('transition')} failed "
                        f"(status {status_code})"
                    )

                _LOGGER.info(
                    "Transition succeeded: %s on %s",
                    body.get("transition"),
                    body.get("id"),
                )
                return {"success": True, "status_code": status_code}

        except aiohttp.ClientError as err:
            _LOGGER.error("Network error during transition: %s", type(err).__name__)
            raise APIError(f"Network error: {type(err).__name__}") from err

    async def get_own_listings(self) -> list[dict[str, Any]]:
        """Fetch all of the authenticated provider's own listings.

        Returns a list of simplified dicts:
        ``{id, title, state, price_aud, deleted, image_url}``.
        """
        await self._ensure_valid_token()
        if not self._access_token:
            raise AuthenticationError("No access token available")

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        params = {
            "per_page": "100",
            "include": "images",
        }

        listings: list[dict[str, Any]] = []
        page = 1
        while True:
            params["page"] = str(page)
            result, _meta = await self._request_with_retry(
                "GET", OWN_LISTINGS_URL, headers=headers, params=params
            )

            data = result.get("data", [])
            included = result.get("included", [])
            images_map = self._build_images_map(included)

            for item in data:
                listing = self._extract_listing(item, images_map)
                if listing is not None:
                    listings.append(listing)

            if len(data) < int(params["per_page"]):
                break
            if page >= MAX_PAGES:
                _LOGGER.warning("Hit MAX_PAGES while fetching own_listings")
                break
            page += 1

        _LOGGER.debug("Fetched %d own listings", len(listings))
        return listings

    @classmethod
    def _build_images_map(
        cls, included: list[dict[str, Any]]
    ) -> dict[str, str]:
        """Build ``{image_id: best_url}`` from the JSON-API included array."""
        images: dict[str, str] = {}
        for item in included:
            if item.get("type") != "image":
                continue
            image_id = cls._extract_uuid(item.get("id"))
            if not image_id:
                continue
            variants = (
                item.get("attributes", {}).get("variants", {}) or {}
            )
            # Prefer a reasonably sized variant; fall back to anything.
            for preferred in ("landscape-crop2x", "landscape-crop", "default"):
                variant = variants.get(preferred)
                if variant and variant.get("url"):
                    images[image_id] = variant["url"]
                    break
            else:
                for variant in variants.values():
                    if isinstance(variant, dict) and variant.get("url"):
                        images[image_id] = variant["url"]
                        break
        return images

    @classmethod
    def _extract_listing(
        cls,
        item: dict[str, Any],
        images_map: dict[str, str],
    ) -> dict[str, Any] | None:
        """Extract a simplified listing dict from one own_listings entry."""
        listing_id = cls._extract_uuid(item.get("id"))
        if not listing_id:
            return None

        attrs = item.get("attributes", {}) or {}
        relationships = item.get("relationships", {}) or {}

        # First image, if any
        image_url: str | None = None
        images_rel = relationships.get("images", {}).get("data") or []
        if isinstance(images_rel, list) and images_rel:
            first_image_id = cls._extract_uuid(images_rel[0].get("id"))
            if first_image_id:
                image_url = images_map.get(first_image_id)

        return {
            "id": listing_id,
            "title": attrs.get("title"),
            "state": attrs.get("state"),
            "deleted": attrs.get("deleted", False),
            "price_aud": cls._format_money(attrs.get("price")),
            "image_url": image_url,
        }

    def _process_transactions(
        self,
        transactions: list[dict[str, Any]],
        included: list[dict[str, Any]],
        diagnostics: dict[str, Any],
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        """Process raw transactions into structured booking data.

        Categorization rules:
        - upcoming: booking_start >= now AND dates are known
        - in_progress: booking_start <= now < booking_end AND dates are known
        - past: booking_end < now AND dates are known
        - unknown: booking_start or booking_end is null/missing

        Returns ALL bookings with a 'category' field.
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

        all_bookings: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        sample_count = 0

        # Store now_utc in diagnostics for verification
        diagnostics["now_utc"] = now.isoformat()

        # Initialize category counts
        diagnostics["upcoming_count"] = 0
        diagnostics["in_progress_count"] = 0
        diagnostics["past_count"] = 0
        diagnostics["unknown_dates_count"] = 0

        for txn in transactions:
            try:
                booking_data, debug_info = self._extract_booking_data(
                    txn, bookings_map, customers_map, listings_map, now, include_sensitive
                )

                # Log first 3 transactions for debugging
                if sample_count < 3:
                    diagnostics["sample_transactions"].append(debug_info)
                    _LOGGER.debug(
                        "Sample transaction [%d]: id=%s, last_transition=%s, "
                        "booking_start=%s, booking_end=%s, category=%s, reason=%s",
                        sample_count,
                        debug_info.get("transaction_id", "unknown"),
                        debug_info.get("last_transition", "unknown"),
                        debug_info.get("booking_start", "missing"),
                        debug_info.get("booking_end", "missing"),
                        debug_info.get("category", "unknown"),
                        debug_info.get("category_reason", "n/a"),
                    )
                    sample_count += 1

                if booking_data:
                    category = debug_info.get("category", "unknown")
                    booking_data["category"] = category
                    booking_data["dates_known"] = category != "unknown"

                    # Update category counts
                    if category == "upcoming":
                        diagnostics["upcoming_count"] += 1
                        diagnostics["total_upcoming"] += 1  # Legacy
                    elif category == "in_progress":
                        diagnostics["in_progress_count"] += 1
                    elif category == "past":
                        diagnostics["past_count"] += 1
                        diagnostics["total_past"] += 1  # Legacy
                    else:  # unknown
                        diagnostics["unknown_dates_count"] += 1
                        diagnostics["total_unknown_dates"] += 1  # Legacy

                    all_bookings.append(booking_data)

            except Exception as err:
                _LOGGER.warning(
                    "Error processing transaction %s: %s",
                    txn.get("id", {}).get("uuid", "unknown"),
                    err,
                )
                continue

        # Sort by booking start date (unknown dates go to end)
        all_bookings.sort(
            key=lambda x: x.get("booking_start") or "9999-12-31T00:00:00Z"
        )

        return all_bookings

    @staticmethod
    def _extract_uuid(node: Any) -> str | None:
        """Extract a UUID string from a Sharetribe id object.

        Handles both ``{"uuid": "..."}`` and bare-string id formats.
        """
        if isinstance(node, dict):
            return node.get("uuid")
        if isinstance(node, str) and node:
            return node
        return None

    @classmethod
    def _related_id(cls, relationships: dict[str, Any], key: str) -> str | None:
        """Pull a related entity id from a relationships dict."""
        ref = relationships.get(key, {}).get("data")
        if not isinstance(ref, dict):
            return None
        return cls._extract_uuid(ref.get("id"))

    @staticmethod
    def _categorize(
        start_dt: datetime | None, end_dt: datetime | None, now: datetime
    ) -> tuple[str, str]:
        """Categorize a booking by its start/end times relative to now.

        Returns ``(category, reason)`` where category is one of
        ``upcoming``, ``in_progress``, ``past``, or ``unknown``.
        """
        if start_dt is None or end_dt is None:
            missing = []
            if start_dt is None:
                missing.append("booking_start")
            if end_dt is None:
                missing.append("booking_end")
            return "unknown", f"missing dates: {', '.join(missing)}"

        if start_dt >= now:
            return "upcoming", (
                f"booking_start ({start_dt.isoformat()}) >= now ({now.isoformat()})"
            )
        if end_dt < now:
            return "past", (
                f"booking_end ({end_dt.isoformat()}) < now ({now.isoformat()})"
            )
        return "in_progress", (
            f"booking_start ({start_dt.isoformat()}) <= now ({now.isoformat()}) "
            f"< booking_end ({end_dt.isoformat()})"
        )

    def _extract_booking_data(
        self,
        txn: dict[str, Any],
        bookings_map: dict[str, dict],
        customers_map: dict[str, dict],
        listings_map: dict[str, dict],
        now: datetime,
        include_sensitive: bool = False,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Extract structured booking data from a transaction.

        Returns ``(booking_data, debug_info)``; ``booking_data`` is None when
        the transaction has no usable id.
        """
        txn_id = self._extract_uuid(txn.get("id"))
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

        # Resolve related entities
        booking_id = self._related_id(relationships, "booking")
        customer_id = self._related_id(relationships, "customer")
        listing_id = self._related_id(relationships, "listing")

        booking = bookings_map.get(booking_id, {}) if booking_id else {}
        booking_attrs = booking.get("attributes", {})
        customer = customers_map.get(customer_id, {}) if customer_id else {}
        customer_profile = customer.get("attributes", {}).get("profile", {})
        listing = listings_map.get(listing_id, {}) if listing_id else {}
        listing_attrs = listing.get("attributes", {})

        # Booking dates and category
        booking_start = booking_attrs.get("start")
        booking_end = booking_attrs.get("end")
        start_dt = parse_iso_datetime(booking_start)
        end_dt = parse_iso_datetime(booking_end)

        if booking_start and start_dt is None:
            _LOGGER.warning(
                "Failed to parse booking_start for transaction %s", txn_id
            )
        if booking_end and end_dt is None:
            _LOGGER.warning(
                "Failed to parse booking_end for transaction %s", txn_id
            )

        category, reason = self._categorize(start_dt, end_dt, now)

        debug_info.update(
            {
                "booking_id": booking_id,
                "booking_start": booking_start,
                "booking_end": booking_end,
                "booking_found_in_included": bool(booking),
                "category": category,
                "category_reason": reason,
                "is_upcoming": category == "upcoming",
                "upcoming_reason": reason,
            }
        )

        # Customer/financial extraction
        protected_data = attrs.get("protectedData", {}) or {}
        customer_obj = self._build_customer_object(
            customer_profile, protected_data, include_sensitive
        )
        raw_phone = (
            protected_data.get("customerPhoneNumber")
            or protected_data.get("phoneNumber")
        )

        booking_data = {
            "transaction_id": txn_id,
            "booking_start": booking_start,
            "booking_end": booking_end,
            # Legacy flat fields (deprecated, use customer object)
            "customer_first_name": customer_profile.get("firstName"),
            "customer_last_name": customer_profile.get("lastName"),
            "customer_display_name": customer_profile.get("displayName"),
            "customer_phone": raw_phone if include_sensitive else self._mask_phone(raw_phone),
            "pickup_address": protected_data.get("pickupAddress")
            or protected_data.get("address"),
            "pickup_suburb": protected_data.get("suburb"),
            "customer": customer_obj,
            "payout_total_aud": self._format_money(attrs.get("payoutTotal")),
            "payin_total_aud": self._format_money(attrs.get("payinTotal")),
            "last_transition": attrs.get("lastTransition"),
            "state": booking_attrs.get("state"),
            "last_transitioned_at": attrs.get("lastTransitionedAt"),
            "listing_title": listing_attrs.get("title"),
            "listing_id": listing_id,
        }

        return booking_data, debug_info

    def _build_customer_object(
        self,
        profile: dict[str, Any],
        protected_data: dict[str, Any],
        include_sensitive: bool,
    ) -> dict[str, Any]:
        """Build structured customer object with optional sensitive data.

        Args:
            profile: Customer profile from user entity.
            protected_data: Transaction protected data.
            include_sensitive: Whether to include sensitive identifiers.

        Returns:
            Structured customer dict with nested licence and address.
        """
        first_name = profile.get("firstName")
        last_name = profile.get("lastName")

        # Phone number - mask if sensitive data disabled
        raw_phone = (
            protected_data.get("customerPhoneNumber")
            or protected_data.get("phoneNumber")
        )
        phone = raw_phone if include_sensitive else self._mask_phone(raw_phone)

        customer: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
        }

        # Address - building + residential address
        building = protected_data.get("building")
        residential_address = protected_data.get("residentialAddress")

        if residential_address or building:
            full_address = residential_address or ""
            if building and full_address:
                full_address = f"{building}, {full_address}"
            elif building:
                full_address = building

            customer["address"] = {
                "building": building,
                "full": full_address if full_address else None,
            }

        # Licence - only include if sensitive data enabled
        if include_sensitive:
            licence_number = protected_data.get("driversLicenceNumber")
            licence_state = protected_data.get("driversLicenceIssuedBy")
            licence_expiry_obj = protected_data.get("driversLicenceExpiryDate")

            if licence_number or licence_state or licence_expiry_obj:
                expiry_iso, expiry_display = self._format_licence_expiry(licence_expiry_obj)
                customer["licence"] = {
                    "number": licence_number,
                    "state": licence_state,
                    "expiry_iso": expiry_iso,
                    "expiry_display": expiry_display,
                }

        return customer

    @staticmethod
    def _mask_phone(phone: str | None) -> str | None:
        """Mask a phone number, showing only first 4 and last 2 digits.

        Example: 0412345678 -> 0412****78
        """
        if not phone:
            return None

        # Remove non-digit characters for processing
        digits = "".join(c for c in phone if c.isdigit())

        if len(digits) < 6:
            # Too short to mask meaningfully
            return "*" * len(phone) if phone else None

        # Show first 4 and last 2 digits
        masked = digits[:4] + "*" * (len(digits) - 6) + digits[-2:]
        return masked

    @staticmethod
    def _format_licence_expiry(
        expiry_obj: dict[str, Any] | None
    ) -> tuple[str | None, str | None]:
        """Format licence expiry date object to ISO and display strings.

        Args:
            expiry_obj: Dict with day, month, year keys.

        Returns:
            Tuple of (iso_date, display_date) e.g. ("2025-12-31", "31/12/2025")
        """
        if not expiry_obj or not isinstance(expiry_obj, dict):
            return None, None

        day = expiry_obj.get("day")
        month = expiry_obj.get("month")
        year = expiry_obj.get("year")

        if not all([day, month, year]):
            return None, None

        try:
            day_int = int(day)
            month_int = int(month)
            year_int = int(year)

            iso_date = f"{year_int:04d}-{month_int:02d}-{day_int:02d}"
            display_date = f"{day_int:02d}/{month_int:02d}/{year_int:04d}"

            return iso_date, display_date
        except (ValueError, TypeError):
            return None, None

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
