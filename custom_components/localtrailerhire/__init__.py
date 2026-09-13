"""The Local Trailer Hire integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import APIError, AuthenticationError, SharetribeFlexAPI
from .auto_review import (
    auto_review_failure_state,
    select_auto_reviews,
    summarize_auto_reviews,
)
from .const import (
    CATEGORY_IN_PROGRESS,
    CATEGORY_UPCOMING,
    CONF_ARCHIVE_MESSAGES,
    CONF_AUTO_REVIEW,
    CONF_AUTO_REVIEW_CONTENT,
    CONF_AUTO_REVIEW_RATING,
    CONF_CLIENT_ID,
    CONF_CUSTOMER_HISTORY_RETENTION,
    CONF_INCLUDE_SENSITIVE,
    CONF_LAST_TRANSITIONS,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONFIRMED_TRANSITIONS,
    DEFAULT_ARCHIVE_MESSAGES,
    DEFAULT_AUTO_REVIEW,
    DEFAULT_CUSTOMER_HISTORY_RETENTION,
    DEFAULT_INCLUDE_SENSITIVE,
    DEFAULT_LAST_TRANSITIONS,
    DEFAULT_REVIEW_CONTENT,
    DEFAULT_REVIEW_RATING,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_BOOKING_CONFIRMED,
    EVENT_BOOKING_REQUEST_RECEIVED,
    EVENT_REVIEW_LEFT,
    LOCALTRAILERHIRE_CLIENT_ID,
    MAX_MESSAGE_SCAN,
    REQUEST_TRANSITIONS,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .customer_history import (
    clear_customer_history,
    merge_customer_history,
    prune_customer_history,
)
from .message_archive import (
    count_archived_messages,
    merge_messages,
    prune_message_archive,
    select_sync_batch,
    summarize_sync_batch,
)
from .services import REGISTERED_SERVICES, async_register_services
from .setup_lifecycle import async_setup_transaction
from .util import parse_iso_datetime

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
]


class LocalTrailerHireStore(Store):
    """Persistent store with schema migration.

    v1 stored ``seen_transitions`` (a flat ``txn_id -> last_transition`` map)
    alongside ``sent_messages``. v2 collapses those into a single
    ``transaction_states`` map keyed by transaction id.
    """

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        if old_major_version < 2:
            seen = old_data.pop("seen_transitions", {}) or {}
            sent = old_data.get("sent_messages", {}) or {}
            transaction_states = old_data.setdefault("transaction_states", {})
            for txn_id, last_transition in seen.items():
                transaction_states.setdefault(
                    txn_id,
                    {
                        "last_transition": last_transition,
                        "last_transitioned_at": None,
                        "message_sent": txn_id in sent,
                        "message_sent_at": sent.get(txn_id),
                        "event_fired_at": None,
                    },
                )
            _LOGGER.info("Migrated %d transactions from storage v1 to v2", len(seen))
        return old_data


async def async_setup(hass: HomeAssistant, _config: dict[str, Any]) -> bool:
    """Set up integration-wide actions before any config entry loads."""
    hass.data.setdefault(DOMAIN, {})
    async_register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Local Trailer Hire from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Initialize storage for tracking sent messages and transaction states.
    # Each config entry gets its own store keyed by entry_id; a single shared
    # key would let multiple provider accounts clobber each other's state.
    # ``LocalTrailerHireStore`` handles schema-version migration on load.
    store = LocalTrailerHireStore(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry.entry_id}")
    stored_data = await store.async_load()

    if stored_data is None:
        # One-time migration: pre-1.2 installs wrote to a single shared key.
        # Only one entry could exist back then (uniqueness keyed on the shared
        # client_id), so the first entry to set up adopts that data and the
        # legacy store is removed.
        legacy_store = LocalTrailerHireStore(hass, STORAGE_VERSION, STORAGE_KEY)
        legacy_data = await legacy_store.async_load()
        if legacy_data:
            _LOGGER.info(
                "Migrating transaction state from legacy shared store to per-entry store for %s",
                entry.entry_id,
            )
            stored_data = legacy_data
            await store.async_save(stored_data)
            await legacy_store.async_remove()

    stored_data = stored_data if isinstance(stored_data, dict) else {}
    for mapping_key in (
        "sent_messages",
        "transaction_states",
        "customer_history",
        "message_history",
    ):
        if not isinstance(stored_data.get(mapping_key), dict):
            stored_data[mapping_key] = {}
    try:
        stored_data["message_sync_cursor"] = max(
            0, int(stored_data.get("message_sync_cursor", 0) or 0)
        )
    except (TypeError, ValueError):
        stored_data["message_sync_cursor"] = 0

    # Get configuration. ``client_id`` is now hardcoded to the LocalTrailerHire
    # marketplace; we still read from entry.data for backwards compat with
    # 1.x installs that stored it explicitly.
    client_id = entry.data.get(CONF_CLIENT_ID) or LOCALTRAILERHIRE_CLIENT_ID
    username = entry.data.get(CONF_USERNAME)
    password = entry.data.get(CONF_PASSWORD)
    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    transitions_str = entry.options.get(CONF_LAST_TRANSITIONS, ",".join(DEFAULT_LAST_TRANSITIONS))
    last_transitions = [t.strip() for t in transitions_str.split(",") if t.strip()]
    include_sensitive = entry.options.get(CONF_INCLUDE_SENSITIVE, DEFAULT_INCLUDE_SENSITIVE)
    history_retention = entry.options.get(
        CONF_CUSTOMER_HISTORY_RETENTION, DEFAULT_CUSTOMER_HISTORY_RETENTION
    )
    archive_messages = entry.options.get(CONF_ARCHIVE_MESSAGES, DEFAULT_ARCHIVE_MESSAGES)
    auto_review = entry.options.get(CONF_AUTO_REVIEW, DEFAULT_AUTO_REVIEW)
    auto_review_rating = entry.options.get(CONF_AUTO_REVIEW_RATING, DEFAULT_REVIEW_RATING)
    auto_review_content = entry.options.get(CONF_AUTO_REVIEW_CONTENT, DEFAULT_REVIEW_CONTENT)

    def persist_refresh_token(token: str) -> None:
        """Persist a rotated token immediately and discard any stored password."""
        if not token or (
            entry.data.get(CONF_REFRESH_TOKEN) == token and CONF_PASSWORD not in entry.data
        ):
            return
        new_data = dict(entry.data)
        new_data[CONF_REFRESH_TOKEN] = token
        new_data.pop(CONF_PASSWORD, None)
        hass.config_entries.async_update_entry(entry, data=new_data)

    # Create API client
    session = async_get_clientsession(hass)
    api = SharetribeFlexAPI(
        session=session,
        client_id=client_id,
        username=username,
        password=password,
        refresh_token=refresh_token,
        refresh_token_callback=persist_refresh_token,
    )

    # Test authentication
    try:
        await api.authenticate()
    except AuthenticationError as err:
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"authentication_{entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="authentication_failed",
        )
        raise ConfigEntryAuthFailed("Authentication failed") from err
    except APIError as err:
        raise ConfigEntryNotReady("API connection failed") from err
    ir.async_delete_issue(hass, DOMAIN, f"authentication_{entry.entry_id}")

    # Persist the rotating refresh token, but never retain the account password
    # after authentication succeeds. Existing installations are scrubbed here
    # on their next successful setup.
    if api.refresh_token:
        persist_refresh_token(api.refresh_token)

    # Create coordinator
    coordinator = LocalTrailerHireCoordinator(
        hass=hass,
        api=api,
        entry=entry,
        last_transitions=last_transitions,
        include_sensitive=include_sensitive,
        history_retention=history_retention,
        archive_messages=archive_messages,
        update_interval=timedelta(minutes=scan_interval),
        store=store,
        stored_data=stored_data,
        auto_review=auto_review,
        auto_review_rating=auto_review_rating,
        auto_review_content=auto_review_content,
    )

    # Publish the runtime object before the initial refresh. That refresh can
    # detect a booking transition and fire an event consumed by automations;
    # their service calls must be able to resolve this entry immediately.
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "store": store,
        "stored_data": stored_data,
    }

    # Register every action before the first scan. A confirmation discovered
    # during startup otherwise reaches its automation while send_message is
    # still absent, records the event as seen, and can permanently miss the
    # customer confirmation.
    await async_setup_transaction(
        hass,
        entry,
        coordinator,
        domain=DOMAIN,
        registered_services=REGISTERED_SERVICES,
        platforms=PLATFORMS,
    )

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


class LocalTrailerHireCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinator for Local Trailer Hire data.

    Transaction State Store structure (per transaction_id):
    {
        "last_transition": str,
        "last_transitioned_at": str (ISO timestamp),
        "message_sent": bool,
        "message_sent_at": str (ISO timestamp) or None,
        "event_fired_at": str (ISO timestamp) or None,
        "request_event_fired_at": str (ISO timestamp) or None,
    }
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: SharetribeFlexAPI,
        entry: ConfigEntry,
        last_transitions: list[str],
        include_sensitive: bool,
        history_retention: str,
        archive_messages: bool,
        update_interval: timedelta,
        store: Store,
        stored_data: dict[str, Any],
        auto_review: bool = False,
        auto_review_rating: int = DEFAULT_REVIEW_RATING,
        auto_review_content: str = DEFAULT_REVIEW_CONTENT,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )
        self.api = api
        self.entry = entry
        self.last_transitions = last_transitions
        self.include_sensitive = include_sensitive
        self.history_retention = history_retention
        self.archive_messages = archive_messages
        self.auto_review = auto_review
        self.auto_review_rating = auto_review_rating
        self.auto_review_content = auto_review_content
        self._store = store
        self._stored_data = stored_data

        # Ensure expected keys exist (storage migration handles legacy data)
        self._stored_data.setdefault("transaction_states", {})
        self._stored_data.setdefault("sent_messages", {})
        self._stored_data.setdefault("customer_history", {})
        self._stored_data.setdefault("message_history", {})
        self._stored_data.setdefault("message_sync_cursor", 0)
        self.customer_history: dict[str, Any] = self._stored_data["customer_history"]
        stored_message_history = self._stored_data["message_history"]
        self.message_history: dict[str, Any] = (
            stored_message_history if isinstance(stored_message_history, dict) else {}
        )
        self._stored_data["message_history"] = self.message_history
        self._message_archive_lock = asyncio.Lock()

        # Listings cache (refreshed each update)
        self.listings: list[dict[str, Any]] = []

        # Reviews cache (refreshed each update) + aggregate rating
        self.reviews: list[dict[str, Any]] = []
        self.average_rating: float | None = None

        # Provider profile + performance stats (current_user)
        self.profile: dict[str, Any] = {}

        # Message-scan results (awaiting reply on active bookings)
        self.awaiting_reply_txns: list[str] = []
        self.latest_message: dict[str, Any] | None = None

        # Diagnostics for debugging
        self.last_fetch_utc: str | None = None
        self.last_success_utc: str | None = None
        self.total_fetched: int = 0
        self.pages_fetched: int = 0
        self.newest_transaction_id: str | None = None
        self.confirmed_new_count: int = 0
        self.request_new_count: int = 0

    async def _async_update_data(self) -> list[dict[str, Any]]:
        """Fetch data from API with detailed debug logging."""
        now = datetime.now(UTC)
        self.last_fetch_utc = now.isoformat()

        try:
            bookings = await self.api.get_transactions(
                last_transitions=self.last_transitions,
                include_sensitive=self.include_sensitive,
            )

            # Retain a bounded, customer-id keyed reference archive. Sensitive
            # contact fields are only kept when explicitly enabled; turning the
            # option off scrubs any values retained by an earlier poll.
            customer_history, history_changed = merge_customer_history(
                self._stored_data.get("customer_history"),
                bookings,
                include_sensitive=self.include_sensitive,
            )
            ir.async_delete_issue(self.hass, DOMAIN, f"authentication_{self.entry.entry_id}")
            customer_history = prune_customer_history(customer_history, self.history_retention, now)
            history_changed = history_changed or customer_history != self.customer_history
            self.customer_history = customer_history
            if history_changed:
                self._stored_data["customer_history"] = customer_history
                await self._store.async_save(self._stored_data)

            # Update diagnostics
            self.last_success_utc = now.isoformat()
            self.total_fetched = len(bookings)
            diagnostics = self.api.diagnostics
            self.pages_fetched = len(diagnostics.get("pages", []))

            # Update refresh token if it changed
            if self.api.refresh_token and (
                self.api.refresh_token != self.entry.data.get(CONF_REFRESH_TOKEN)
                or CONF_PASSWORD in self.entry.data
            ):
                new_data = dict(self.entry.data)
                new_data[CONF_REFRESH_TOKEN] = self.api.refresh_token
                new_data.pop(CONF_PASSWORD, None)
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)

            # Detect newly received booking requests and fire events
            self.request_new_count = await self._detect_booking_requests(bookings)

            # Detect newly confirmed bookings and fire events
            confirmed_count = await self._detect_confirmed_bookings(bookings)
            self.confirmed_new_count = confirmed_count

            # Refresh own_listings (best-effort; failures don't fail the update)
            try:
                self.listings = await self.api.get_own_listings()
            except (APIError, AuthenticationError) as err:
                _LOGGER.warning("Failed to refresh own_listings: %s", err)

            # Refresh provider profile (best-effort; also caches the user id)
            try:
                self.profile = await self.api.get_current_user()
            except (APIError, AuthenticationError) as err:
                _LOGGER.warning("Failed to refresh profile: %s", err)

            # Refresh reviews + aggregate rating (best-effort)
            try:
                self.reviews = await self.api.get_reviews()
                self.average_rating = self.api.average_rating(self.reviews)
            except (APIError, AuthenticationError) as err:
                _LOGGER.warning("Failed to refresh reviews: %s", err)

            # Scan active bookings for unanswered customer messages (best-effort)
            try:
                scanned_message_ids = await self._refresh_awaiting_replies(bookings)
            except Exception:
                _LOGGER.exception("Awaiting-reply scan failed")
                scanned_message_ids = set()

            if self.archive_messages:
                try:
                    await self.sync_message_history(
                        min(5, MAX_MESSAGE_SCAN),
                        bookings=bookings,
                        excluded_transaction_ids=scanned_message_ids,
                    )
                except Exception:
                    _LOGGER.exception("Incremental message archive sync failed")

            # Native auto-review pass (opt-in). Best-effort: a failure here must
            # never fail the data update.
            if self.auto_review:
                try:
                    await self._run_auto_review(bookings, now)
                except Exception:
                    _LOGGER.exception("Auto-review pass failed")
            else:
                ir.async_delete_issue(self.hass, DOMAIN, f"auto_review_{self.entry.entry_id}")

            # Find newest transaction by last_transitioned_at
            newest_txn = self._find_newest_transaction(bookings)
            if newest_txn:
                self.newest_transaction_id = newest_txn.get("transaction_id")

            # Debug logging: summary of refresh
            _LOGGER.debug(
                "Refresh ok: fetched=%d pages=%d newest_last_transitioned_at=%s confirmed_new=%d",
                self.total_fetched,
                self.pages_fetched,
                newest_txn.get("last_transitioned_at") if newest_txn else "none",
                confirmed_count,
            )

            # Debug logging: newest 5 transactions
            self._log_newest_transactions(bookings, count=5)

            return bookings

        except AuthenticationError as err:
            # Trigger reauth flow
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"authentication_{self.entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key="authentication_failed",
            )
            raise ConfigEntryAuthFailed("Authentication failed") from err

        except APIError as err:
            raise UpdateFailed(f"API error: {err}") from err

        except Exception as err:
            _LOGGER.exception("Unexpected error fetching data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    def _find_newest_transaction(self, bookings: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find the transaction with the most recent last_transitioned_at."""
        newest = None
        newest_dt = None

        for booking in bookings:
            dt = parse_iso_datetime(booking.get("last_transitioned_at"))
            if dt is None:
                continue
            if newest_dt is None or dt > newest_dt:
                newest_dt = dt
                newest = booking

        return newest

    def _log_newest_transactions(self, bookings: list[dict[str, Any]], count: int = 5) -> None:
        """Log the N newest transactions by last_transitioned_at for debugging."""
        # Sort by last_transitioned_at descending
        sorted_bookings = sorted(
            [b for b in bookings if b.get("last_transitioned_at")],
            key=lambda x: x.get("last_transitioned_at", ""),
            reverse=True,
        )

        for i, booking in enumerate(sorted_bookings[:count]):
            _LOGGER.debug(
                "Newest[%d]: txn=%s transition=%s transitioned_at=%s listing=%s",
                i,
                booking.get("transaction_id", "?")[:8],  # First 8 chars of UUID
                booking.get("last_transition", "?"),
                booking.get("last_transitioned_at", "?"),
                booking.get("listing_title", "?")[:30],  # Truncate listing title
            )

    async def _detect_confirmed_bookings(self, bookings: list[dict[str, Any]]) -> int:
        """Detect newly confirmed bookings and fire events.

        A booking is considered "newly confirmed" when:
        1. Its last_transition is in CONFIRMED_TRANSITIONS (is_confirmed)
        2. AND one of the following:
           a. We haven't seen this transaction before (previously is None)
           b. The last_transitioned_at timestamp changed
           c. The previous last_transition was NOT in CONFIRMED_TRANSITIONS
        3. AND message_sent is False (to prevent duplicate events if message already sent)

        Returns the count of new confirmations detected.
        """
        now = datetime.now(UTC)
        transaction_states = self._stored_data.get("transaction_states", {})
        changes_made = False
        confirmed_count = 0

        for booking in bookings:
            txn_id = booking.get("transaction_id")
            last_transition = booking.get("last_transition")
            last_transitioned_at = booking.get("last_transitioned_at")

            if not txn_id or not last_transition:
                continue

            # Check if this is a confirmed transition
            is_confirmed = last_transition in CONFIRMED_TRANSITIONS

            if not is_confirmed:
                # Still update state tracking even for non-confirmed transitions
                # so we can detect when a non-confirmed -> confirmed transition happens
                if txn_id not in transaction_states:
                    transaction_states[txn_id] = {
                        "last_transition": last_transition,
                        "last_transitioned_at": last_transitioned_at,
                        "message_sent": False,
                        "message_sent_at": None,
                        "event_fired_at": None,
                    }
                    changes_made = True
                elif transaction_states[txn_id].get("last_transitioned_at") != last_transitioned_at:
                    transaction_states[txn_id]["last_transition"] = last_transition
                    transaction_states[txn_id]["last_transitioned_at"] = last_transitioned_at
                    changes_made = True
                continue

            # This is a confirmed transition - check if it's newly confirmed
            previously = transaction_states.get(txn_id)

            is_new_confirmation = False
            reason = ""

            if previously is None:
                # Never seen this transaction
                is_new_confirmation = True
                reason = "new_transaction"
            elif previously.get("last_transitioned_at") != last_transitioned_at:
                # Timestamp changed - this could be a re-confirmation or modification
                is_new_confirmation = True
                reason = f"timestamp_changed (old={previously.get('last_transitioned_at')})"
            elif previously.get("last_transition") not in CONFIRMED_TRANSITIONS:
                # Transition changed from non-confirmed to confirmed
                is_new_confirmation = True
                reason = f"transition_changed (old={previously.get('last_transition')})"

            # Check if message was already sent for this transaction
            # (idempotent protection - don't fire event again if message sent)
            if is_new_confirmation and previously and previously.get("message_sent"):
                _LOGGER.debug(
                    "Skipping event for txn=%s: message already sent at %s",
                    txn_id,
                    previously.get("message_sent_at"),
                )
                # Still update the state
                transaction_states[txn_id] = {
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "message_sent": True,
                    "message_sent_at": previously.get("message_sent_at"),
                    "event_fired_at": previously.get("event_fired_at"),
                }
                changes_made = True
                continue

            if is_new_confirmation:
                confirmed_count += 1

                _LOGGER.info(
                    "Booking confirmed: txn=%s transition=%s listing=%s",
                    txn_id,
                    last_transition,
                    booking.get("listing_title", ""),
                )
                _LOGGER.debug(
                    "Confirmation reason=%s, transitioned_at=%s",
                    reason,
                    last_transitioned_at,
                )

                # Fire event
                event_data = {
                    "transaction_id": txn_id,
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "customer_first_name": booking.get("customer_first_name"),
                    "customer_display_name": booking.get("customer_display_name"),
                    "listing_title": booking.get("listing_title"),
                    "listing_id": booking.get("listing_id"),
                    "booking_start": booking.get("booking_start"),
                    "booking_end": booking.get("booking_end"),
                    "payout_total_aud": booking.get("payout_total_aud"),
                    "timestamp": now.isoformat(),
                }
                self.hass.bus.async_fire(EVENT_BOOKING_CONFIRMED, event_data)

                # Update state
                transaction_states[txn_id] = {
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "message_sent": False,
                    "message_sent_at": None,
                    "event_fired_at": now.isoformat(),
                }
                changes_made = True
            else:
                # Not a new confirmation, but update state if needed
                if txn_id not in transaction_states:
                    transaction_states[txn_id] = {
                        "last_transition": last_transition,
                        "last_transitioned_at": last_transitioned_at,
                        "message_sent": False,
                        "message_sent_at": None,
                        "event_fired_at": None,
                    }
                    changes_made = True

        # Persist changes to storage
        if changes_made:
            self._stored_data["transaction_states"] = transaction_states
            await self._store.async_save(self._stored_data)

        return confirmed_count

    async def _detect_booking_requests(self, bookings: list[dict[str, Any]]) -> int:
        """Detect newly received booking requests and fire events.

        A request is "newly received" when ``last_transition`` is in
        ``REQUEST_TRANSITIONS`` and we have not already fired the request
        event for that transitioned_at value.
        """
        now = datetime.now(UTC)
        transaction_states = self._stored_data.get("transaction_states", {})
        changes_made = False
        request_count = 0

        for booking in bookings:
            txn_id = booking.get("transaction_id")
            last_transition = booking.get("last_transition")
            last_transitioned_at = booking.get("last_transitioned_at")

            if not txn_id or last_transition not in REQUEST_TRANSITIONS:
                continue

            previously = transaction_states.get(txn_id)
            already_fired_at = previously.get("request_event_fired_at") if previously else None
            already_fired_for_same_transition = (
                already_fired_at is not None
                and previously is not None
                and previously.get("last_transitioned_at") == last_transitioned_at
            )
            if already_fired_for_same_transition:
                continue

            request_count += 1
            _LOGGER.info(
                "Booking request received: txn=%s transition=%s listing=%s",
                txn_id,
                last_transition,
                booking.get("listing_title", ""),
            )

            event_data = {
                "transaction_id": txn_id,
                "last_transition": last_transition,
                "last_transitioned_at": last_transitioned_at,
                "customer_first_name": booking.get("customer_first_name"),
                "customer_display_name": booking.get("customer_display_name"),
                "listing_title": booking.get("listing_title"),
                "listing_id": booking.get("listing_id"),
                "booking_start": booking.get("booking_start"),
                "booking_end": booking.get("booking_end"),
                "payout_total_aud": booking.get("payout_total_aud"),
                "timestamp": now.isoformat(),
            }
            self.hass.bus.async_fire(EVENT_BOOKING_REQUEST_RECEIVED, event_data)

            new_state = (
                dict(previously)
                if previously
                else {
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "message_sent": False,
                    "message_sent_at": None,
                    "event_fired_at": None,
                }
            )
            new_state["last_transition"] = last_transition
            new_state["last_transitioned_at"] = last_transitioned_at
            new_state["request_event_fired_at"] = now.isoformat()
            transaction_states[txn_id] = new_state
            changes_made = True

        if changes_made:
            self._stored_data["transaction_states"] = transaction_states
            await self._store.async_save(self._stored_data)

        return request_count

    async def fire_confirmed_events_since(
        self,
        cutoff: datetime,
        dry_run: bool = False,
    ) -> int:
        """Re-fire confirmed events for bookings transitioned since cutoff.

        This is a debugging tool to re-trigger events without sending messages.

        Args:
            cutoff: Only fire events for transactions transitioned after this time.
            dry_run: If True, just log what would be fired without actually firing.

        Returns:
            Number of events fired (or would be fired if dry_run).
        """
        if not self.data:
            _LOGGER.warning("No data available to fire events")
            return 0

        now = datetime.now(UTC)
        fired_count = 0

        for booking in self.data:
            last_transition = booking.get("last_transition")
            last_transitioned_at = booking.get("last_transitioned_at")
            txn_id = booking.get("transaction_id")

            if not last_transition or last_transition not in CONFIRMED_TRANSITIONS:
                continue

            transitioned_dt = parse_iso_datetime(last_transitioned_at)
            if transitioned_dt is None:
                continue

            if transitioned_dt < cutoff:
                continue

            fired_count += 1

            if dry_run:
                _LOGGER.info(
                    "[DRY RUN] Would fire event for txn=%s, transition=%s, at=%s",
                    txn_id,
                    last_transition,
                    last_transitioned_at,
                )
            else:
                _LOGGER.info(
                    "REPLAY EVENT FIRED: %s - txn=%s, transition=%s, at=%s",
                    EVENT_BOOKING_CONFIRMED,
                    txn_id,
                    last_transition,
                    last_transitioned_at,
                )
                event_data = {
                    "transaction_id": txn_id,
                    "last_transition": last_transition,
                    "last_transitioned_at": last_transitioned_at,
                    "customer_first_name": booking.get("customer_first_name"),
                    "customer_display_name": booking.get("customer_display_name"),
                    "listing_title": booking.get("listing_title"),
                    "listing_id": booking.get("listing_id"),
                    "booking_start": booking.get("booking_start"),
                    "booking_end": booking.get("booking_end"),
                    "payout_total_aud": booking.get("payout_total_aud"),
                    "timestamp": now.isoformat(),
                    "is_replay": True,
                }
                self.hass.bus.async_fire(EVENT_BOOKING_CONFIRMED, event_data)

        _LOGGER.info(
            "fire_confirmed_events_since: cutoff=%s, fired=%d, dry_run=%s",
            cutoff.isoformat(),
            fired_count,
            dry_run,
        )
        return fired_count

    async def mark_message_sent(self, transaction_id: str) -> None:
        """Mark a transaction as having had a message sent."""
        transaction_states = self._stored_data.get("transaction_states", {})
        now_iso = datetime.now(UTC).isoformat()

        if transaction_id in transaction_states:
            transaction_states[transaction_id]["message_sent"] = True
            transaction_states[transaction_id]["message_sent_at"] = now_iso
        else:
            # Create new entry
            transaction_states[transaction_id] = {
                "last_transition": None,
                "last_transitioned_at": None,
                "message_sent": True,
                "message_sent_at": now_iso,
                "event_fired_at": None,
            }

        self._stored_data["transaction_states"] = transaction_states
        await self._store.async_save(self._stored_data)
        _LOGGER.debug("Marked message_sent=True for transaction %s", transaction_id)

    async def clear_customer_history(self, scope: str = "all") -> None:
        """Delete the archive or actively scrub its sensitive fields."""
        self.customer_history = clear_customer_history(self.customer_history, scope)
        self._stored_data["customer_history"] = self.customer_history
        await self._store.async_save(self._stored_data)

    async def clear_message_history(self) -> None:
        """Delete all retained message content and reset the backfill cursor."""
        async with self._message_archive_lock:
            self.message_history = {}
            self._stored_data["message_history"] = {}
            self._stored_data["message_sync_cursor"] = 0
            await self._store.async_save(self._stored_data)

    async def sync_message_history(
        self,
        batch_size: int = 10,
        *,
        bookings: list[dict[str, Any]] | None = None,
        excluded_transaction_ids: set[str] | frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """Incrementally sync a rotating bounded batch of conversations."""
        source = bookings if bookings is not None else (self.data or [])
        transaction_ids = [
            str(item["transaction_id"])
            for item in source
            if item.get("transaction_id")
            and str(item["transaction_id"]) not in excluded_transaction_ids
        ]
        if not transaction_ids:
            return summarize_sync_batch(
                total_conversations=0,
                selected_transaction_ids=[],
                completed_transaction_ids=set(),
                partial_transaction_ids=set(),
                failed_transaction_ids=set(),
                new_messages=0,
            )

        async with self._message_archive_lock:
            cursor = int(self._stored_data.get("message_sync_cursor", 0) or 0)
            selected, next_cursor = select_sync_batch(transaction_ids, batch_size, cursor)
            archive = self.message_history
            archive_changed = False
            added = 0
            completed_ids: set[str] = set()
            partial_ids: set[str] = set()
            failed_ids: set[str] = set()
            for txn_id in selected:
                raw_record = archive.get(txn_id)
                record = raw_record if isinstance(raw_record, dict) else {}
                raw_messages = record.get("messages")
                stored_messages = raw_messages if isinstance(raw_messages, dict) else {}
                known_ids = frozenset(str(message_id) for message_id in stored_messages)
                resume_after_id = (
                    record.get("backfill_anchor_id")
                    if record.get("sync_status") == "partial"
                    else None
                )
                try:
                    messages, complete, next_anchor = await self.api.get_messages_incremental(
                        txn_id,
                        known_ids,
                        max_pages=3,
                        resume_after_id=resume_after_id,
                    )
                except (APIError, AuthenticationError):
                    archive, changed = merge_messages(archive, txn_id, [], sync_error=True)
                    archive_changed = archive_changed or changed
                    failed_ids.add(txn_id)
                    continue
                before = len(known_ids)
                archive, changed = merge_messages(
                    archive,
                    txn_id,
                    messages,
                    sync_complete=complete,
                    backfill_anchor_id=next_anchor,
                )
                archive_changed = archive_changed or changed
                updated_record = archive.get(txn_id)
                updated_messages = (
                    updated_record.get("messages", {}) if isinstance(updated_record, dict) else {}
                )
                added += max(0, len(updated_messages) - before)
                if complete:
                    completed_ids.add(txn_id)
                else:
                    partial_ids.add(txn_id)

            pruned = prune_message_archive(archive, self.history_retention)
            archive_changed = archive_changed or pruned != archive
            archive = pruned
            self.message_history = archive
            self._stored_data["message_history"] = archive
            cursor_changed = next_cursor != self._stored_data.get("message_sync_cursor", 0)
            self._stored_data["message_sync_cursor"] = next_cursor
            if archive_changed or cursor_changed:
                await self._store.async_save(self._stored_data)
        return summarize_sync_batch(
            total_conversations=len(transaction_ids),
            selected_transaction_ids=selected,
            completed_transaction_ids=completed_ids,
            partial_transaction_ids=partial_ids,
            failed_transaction_ids=failed_ids,
            new_messages=added,
        )

    async def _run_auto_review(
        self,
        bookings: list[dict[str, Any]],
        now: datetime,
        force_ids: set[str] | None = None,
    ) -> dict[str, int]:
        """Attempt provider reviews on eligible past bookings (opt-in).

        Selection is pure (see ``auto_review.select_auto_reviews``). For each
        selected transaction we attempt ``leave_review`` and let the API decide
        whether the review window is open: success is recorded in the store so it
        never re-posts, and failures use persisted exponential backoff on later
        polls. State persistence is what makes this survive restarts.
        """
        transaction_states = self._stored_data.get("transaction_states", {})
        to_review = select_auto_reviews(
            bookings,
            transaction_states,
            enabled=self.auto_review or force_ids is not None,
            now=now,
            ignore_backoff=force_ids is not None,
        )
        if force_ids is not None:
            to_review = [txn_id for txn_id in to_review if txn_id in force_ids]
        if not to_review:
            self._update_auto_review_repair()
            return {"attempted": 0, "posted": 0, "failed": 0}

        changed = False
        posted = 0
        failed = 0
        for txn_id in to_review:
            state = transaction_states.setdefault(txn_id, {})
            try:
                result = await self.api.leave_review(
                    txn_id,
                    rating=self.auto_review_rating,
                    content=self.auto_review_content,
                )
            except (APIError, AuthenticationError) as err:
                # Window likely not open yet (or transient). Persist the retry
                # schedule so frequent coordinator polls cannot exhaust the
                # booking's opportunity before Sharetribe opens the transition.
                safe_failure = f"{type(err).__name__}: {str(err)[:160]}"
                state.update(auto_review_failure_state(state, now, safe_failure))
                changed = True
                failed += 1
                _LOGGER.debug(
                    "Auto-review attempt %d failed for %s: %s",
                    state["auto_review_attempts"],
                    txn_id,
                    err,
                )
                continue

            state["auto_reviewed"] = True
            state["auto_reviewed_at"] = now.isoformat()
            state["auto_review_transition"] = result.get("transition")
            state.pop("auto_review_next_attempt_at", None)
            state.pop("auto_review_last_failure", None)
            changed = True
            posted += 1
            self.hass.bus.async_fire(
                EVENT_REVIEW_LEFT,
                {
                    "transaction_id": txn_id,
                    "transition": result.get("transition"),
                    "rating": self.auto_review_rating,
                    "auto": True,
                    "timestamp": now.isoformat(),
                },
            )
            _LOGGER.info("Auto-review posted for %s (%s)", txn_id, result.get("transition"))

        if changed:
            self._stored_data["transaction_states"] = transaction_states
            await self._store.async_save(self._stored_data)
        self._update_auto_review_repair()
        return {"attempted": len(to_review), "posted": posted, "failed": failed}

    def auto_review_dry_run(self, transaction_id: str | None = None) -> dict[str, Any]:
        """Return eligible transaction ids without mutating Sharetribe or storage."""
        now = datetime.now(UTC)
        candidates = select_auto_reviews(
            self.data or [],
            self._stored_data.get("transaction_states", {}),
            enabled=True,
            now=now,
            ignore_backoff=True,
        )
        if transaction_id:
            candidates = [item for item in candidates if item == transaction_id]
        due_now = select_auto_reviews(
            self.data or [],
            self._stored_data.get("transaction_states", {}),
            enabled=True,
            now=now,
        )
        return {
            "enabled": self.auto_review,
            "candidate_count": len(candidates),
            "candidate_transaction_ids": candidates,
            "due_now_count": len([item for item in candidates if item in due_now]),
            "checked_at": now.isoformat(),
        }

    async def retry_auto_reviews_now(self, transaction_id: str | None = None) -> dict[str, Any]:
        """Immediately retry one explicitly selected review transaction."""
        if not transaction_id:
            raise HomeAssistantError(
                "transaction_id is required; use auto_review_dry_run to inspect candidates"
            )
        dry_run = self.auto_review_dry_run(transaction_id)
        force_ids = set(dry_run["candidate_transaction_ids"])
        result = await self._run_auto_review(self.data or [], datetime.now(UTC), force_ids)
        return {**result, "requested": len(force_ids)}

    def _update_auto_review_repair(self) -> None:
        """Raise one actionable Repair after repeated sanitized failures."""
        if not self.auto_review:
            ir.async_delete_issue(self.hass, DOMAIN, f"auto_review_{self.entry.entry_id}")
            return
        failing = sum(
            1
            for state in self._stored_data.get("transaction_states", {}).values()
            if not state.get("auto_reviewed") and state.get("auto_review_attempts", 0) >= 3
        )
        issue_id = f"auto_review_{self.entry.entry_id}"
        if not failing:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key="auto_review_failed",
            translation_placeholders={"count": str(failing)},
        )

    def has_message_been_sent(self, transaction_id: str) -> bool:
        """Check if a message has already been sent for a transaction."""
        transaction_states = self._stored_data.get("transaction_states", {})
        state = transaction_states.get(transaction_id)
        if state:
            return state.get("message_sent", False)
        return False

    @property
    def auto_review_status(self) -> dict[str, Any]:
        """At-a-glance auto-review status for the diagnostic sensor."""
        status = summarize_auto_reviews(
            self._stored_data.get("transaction_states", {}),
            enabled=self.auto_review,
            rating=self.auto_review_rating,
        )
        dry_run = self.auto_review_dry_run()
        status["candidate_count"] = dry_run["candidate_count"]
        status["due_now_count"] = dry_run["due_now_count"]
        return status

    async def _refresh_awaiting_replies(self, bookings: list[dict[str, Any]]) -> set[str]:
        """Flag active bookings whose latest message awaits a host reply.

        Bounded to ``MAX_MESSAGE_SCAN`` active (upcoming/in_progress) bookings to
        keep per-poll API calls in check. Updates ``awaiting_reply_txns`` and
        ``latest_message`` (newest message across the scanned set).
        """
        provider_id = await self.api.get_current_user_id()
        active = [
            b
            for b in bookings
            if b.get("category") in (CATEGORY_UPCOMING, CATEGORY_IN_PROGRESS)
            and b.get("transaction_id")
        ][:MAX_MESSAGE_SCAN]

        async def _scan() -> set[str]:
            awaiting: list[str] = []
            latest: dict[str, Any] | None = None
            latest_ts = ""
            archive_changed = False
            scanned: set[str] = set()
            for booking in active:
                txn_id = str(booking["transaction_id"])
                scanned.add(txn_id)
                try:
                    if self.archive_messages:
                        raw_record = self.message_history.get(txn_id)
                        record = raw_record if isinstance(raw_record, dict) else {}
                        raw_messages = record.get("messages")
                        stored_messages = raw_messages if isinstance(raw_messages, dict) else {}
                        known = frozenset(str(message_id) for message_id in stored_messages)
                        resume_after_id = (
                            record.get("backfill_anchor_id")
                            if record.get("sync_status") == "partial"
                            else None
                        )
                        (
                            new_messages,
                            complete,
                            next_anchor,
                        ) = await self.api.get_messages_incremental(
                            txn_id,
                            known,
                            max_pages=2,
                            resume_after_id=resume_after_id,
                        )
                        self.message_history, changed = merge_messages(
                            self.message_history,
                            txn_id,
                            new_messages,
                            sync_complete=complete,
                            backfill_anchor_id=next_anchor,
                        )
                        archive_changed = archive_changed or changed
                        updated_record = self.message_history.get(txn_id)
                        updated_messages = (
                            updated_record.get("messages", {})
                            if isinstance(updated_record, dict)
                            else {}
                        )
                        messages = list(updated_messages.values())
                    else:
                        messages = await self.api.get_messages(txn_id)
                except (APIError, AuthenticationError) as err:
                    _LOGGER.debug("Message fetch failed for %s: %s", txn_id, err)
                    continue
                if self.api.awaiting_reply(messages, provider_id):
                    awaiting.append(txn_id)
                msg = self.api.latest_message(messages)
                if msg and (msg.get("created_at") or "") > latest_ts:
                    latest_ts = msg.get("created_at") or ""
                    latest = {
                        **msg,
                        "transaction_id": txn_id,
                        "listing_title": booking.get("listing_title"),
                    }

            self.awaiting_reply_txns = awaiting
            self.latest_message = latest
            if self.archive_messages:
                pruned = prune_message_archive(self.message_history, self.history_retention)
                archive_changed = archive_changed or pruned != self.message_history
                self.message_history = pruned
                if archive_changed:
                    self._stored_data["message_history"] = self.message_history
                    await self._store.async_save(self._stored_data)
            return scanned

        if not self.archive_messages:
            return await _scan()
        async with self._message_archive_lock:
            return await _scan()

    def get_diagnostics(self) -> dict[str, Any]:
        """Get diagnostic information for debugging."""
        return {
            "last_fetch_utc": self.last_fetch_utc,
            "last_success_utc": self.last_success_utc,
            "total_fetched": self.total_fetched,
            "pages_fetched": self.pages_fetched,
            "newest_transaction_id": self.newest_transaction_id,
            "confirmed_new_count": self.confirmed_new_count,
            "customer_history_count": len(self.customer_history),
            "message_history_conversation_count": len(self.message_history),
            "message_history_message_count": count_archived_messages(self.message_history),
            "history_retention": self.history_retention,
            "archive_messages": self.archive_messages,
            "auto_review": self.auto_review_status,
            "transaction_states_count": len(self._stored_data.get("transaction_states", {})),
            "update_interval_seconds": self.update_interval.total_seconds()
            if self.update_interval
            else None,
        }
