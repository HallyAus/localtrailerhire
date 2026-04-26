"""Sensor platform for Local Trailer Hire integration."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_DOLLAR
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LocalTrailerHireCoordinator
from .util import parse_iso_datetime
from .const import (
    ATTR_BOOKING_COUNT,
    ATTR_BOOKINGS,
    ATTR_BREAKDOWN,
    ATTR_LAST_UPDATE,
    CATEGORY_IN_PROGRESS,
    CATEGORY_PAST,
    CATEGORY_UNKNOWN,
    CATEGORY_UPCOMING,
    CONF_INCLUDE_BOOKING_LISTS,
    DEFAULT_INCLUDE_BOOKING_LISTS,
    DOMAIN,
    PAYOUT_TRANSITIONS,
    REQUEST_TRANSITIONS,
    SENSOR_BOOKINGS_TOTAL_PAYIN,
    SENSOR_EARNINGS_EARNED,
    SENSOR_EARNINGS_SCHEDULED,
    SENSOR_EARNINGS_TOTAL,
    SENSOR_IN_PROGRESS_COUNT,
    SENSOR_NEXT_CUSTOMER,
    SENSOR_NEXT_END,
    SENSOR_NEXT_PAYOUT,
    SENSOR_NEXT_START,
    SENSOR_TOTAL_COUNT,
    SENSOR_UNKNOWN_DATES_COUNT,
    SENSOR_UPCOMING_COUNT,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Local Trailer Hire sensors."""
    coordinator: LocalTrailerHireCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    entities: list[SensorEntity] = [
        # Count sensors
        UpcomingBookingsCountSensor(coordinator, entry),
        InProgressBookingsCountSensor(coordinator, entry),
        UnknownDatesCountSensor(coordinator, entry),
        TotalBookingsCountSensor(coordinator, entry),
        PendingRequestCountSensor(coordinator, entry),
        # Next booking sensors
        NextBookingStartSensor(coordinator, entry),
        NextBookingEndSensor(coordinator, entry),
        NextBookingCustomerSensor(coordinator, entry),
        NextBookingPayoutSensor(coordinator, entry),
        # Earnings sensors
        EarningsTotalSensor(coordinator, entry),
        EarningsEarnedSensor(coordinator, entry),
        EarningsScheduledSensor(coordinator, entry),
        BookingsTotalPayinSensor(coordinator, entry),
        EarningsLast30DaysSensor(coordinator, entry),
        EarningsMonthToDateSensor(coordinator, entry),
        EarningsYearToDateSensor(coordinator, entry),
    ]

    # Per-listing entities (created from the initial listings snapshot)
    for listing in coordinator.listings:
        listing_id = listing.get("id")
        if not listing_id:
            continue
        entities.append(ListingStateSensor(coordinator, entry, listing_id))
        entities.append(ListingPriceSensor(coordinator, entry, listing_id))
        entities.append(ListingBookingsCountSensor(coordinator, entry, listing_id))

    async_add_entities(entities)


class LocalTrailerHireBaseSensor(
    CoordinatorEntity[LocalTrailerHireCoordinator], SensorEntity
):
    """Base class for Local Trailer Hire sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LocalTrailerHireCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Local Trailer Hire",
            manufacturer="Sharetribe",
            model="Flex Marketplace",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _all_bookings(self) -> list[dict[str, Any]]:
        """Get all bookings from coordinator."""
        if self.coordinator.data:
            return self.coordinator.data
        return []

    @property
    def _upcoming_bookings(self) -> list[dict[str, Any]]:
        """Get only upcoming bookings (category == 'upcoming')."""
        return [b for b in self._all_bookings if b.get("category") == CATEGORY_UPCOMING]

    @property
    def _in_progress_bookings(self) -> list[dict[str, Any]]:
        """Get only in-progress bookings (category == 'in_progress')."""
        return [b for b in self._all_bookings if b.get("category") == CATEGORY_IN_PROGRESS]

    @property
    def _past_bookings(self) -> list[dict[str, Any]]:
        """Get only past bookings (category == 'past')."""
        return [b for b in self._all_bookings if b.get("category") == CATEGORY_PAST]

    @property
    def _unknown_dates_bookings(self) -> list[dict[str, Any]]:
        """Get only bookings with unknown dates (category == 'unknown')."""
        return [b for b in self._all_bookings if b.get("category") == CATEGORY_UNKNOWN]

    @property
    def _next_upcoming_booking(self) -> dict[str, Any] | None:
        """Get the next upcoming booking (soonest start among category == 'upcoming')."""
        upcoming = self._upcoming_bookings
        if not upcoming:
            return None
        # Already sorted by booking_start in API
        return upcoming[0]

    @property
    def _include_booking_lists(self) -> bool:
        """Check if booking lists should be included in attributes."""
        return self._entry.options.get(
            CONF_INCLUDE_BOOKING_LISTS, DEFAULT_INCLUDE_BOOKING_LISTS
        )


# =============================================================================
# COUNT SENSORS
# =============================================================================


class UpcomingBookingsCountSensor(LocalTrailerHireBaseSensor):
    """Sensor for count of upcoming bookings."""

    _attr_icon = "mdi:calendar-clock"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, SENSOR_UPCOMING_COUNT, "Upcoming Bookings")

    @property
    def native_value(self) -> int:
        """Return the count of upcoming bookings."""
        return len(self._upcoming_bookings)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        attrs: dict[str, Any] = {
            ATTR_BOOKING_COUNT: len(self._upcoming_bookings),
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
        }

        # Include bookings list if enabled
        if self._include_booking_lists:
            attrs[ATTR_BOOKINGS] = self._upcoming_bookings

        return attrs


class InProgressBookingsCountSensor(LocalTrailerHireBaseSensor):
    """Sensor for count of in-progress bookings."""

    _attr_icon = "mdi:calendar-check"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator, entry, SENSOR_IN_PROGRESS_COUNT, "In Progress Bookings"
        )

    @property
    def native_value(self) -> int:
        """Return the count of in-progress bookings."""
        return len(self._in_progress_bookings)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        attrs: dict[str, Any] = {
            ATTR_BOOKING_COUNT: len(self._in_progress_bookings),
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
        }

        # Include bookings list if enabled
        if self._include_booking_lists:
            attrs[ATTR_BOOKINGS] = self._in_progress_bookings

        return attrs


class UnknownDatesCountSensor(LocalTrailerHireBaseSensor):
    """Sensor for count of bookings with unknown dates."""

    _attr_icon = "mdi:calendar-question"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator, entry, SENSOR_UNKNOWN_DATES_COUNT, "Unknown Dates Bookings"
        )

    @property
    def native_value(self) -> int:
        """Return the count of bookings with unknown dates."""
        return len(self._unknown_dates_bookings)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        attrs: dict[str, Any] = {
            ATTR_BOOKING_COUNT: len(self._unknown_dates_bookings),
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
        }

        # Include bookings list if enabled
        if self._include_booking_lists:
            attrs[ATTR_BOOKINGS] = self._unknown_dates_bookings

        return attrs


class TotalBookingsCountSensor(LocalTrailerHireBaseSensor):
    """Sensor for total count of all fetched bookings."""

    _attr_icon = "mdi:calendar-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, SENSOR_TOTAL_COUNT, "Total Bookings")

    @property
    def native_value(self) -> int:
        """Return the total count of all fetched bookings."""
        return len(self._all_bookings)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes with breakdown."""
        attrs: dict[str, Any] = {
            ATTR_BOOKING_COUNT: len(self._all_bookings),
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            ATTR_BREAKDOWN: {
                "upcoming": len(self._upcoming_bookings),
                "in_progress": len(self._in_progress_bookings),
                "past": len(self._past_bookings),
                "unknown_dates": len(self._unknown_dates_bookings),
            },
        }

        # Add diagnostics info if available
        api = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("api")
        if api and hasattr(api, "diagnostics"):
            diag = api.diagnostics
            if diag:
                attrs["_diagnostics"] = {
                    "last_fetch": diag.get("request_time"),
                    "now_utc": diag.get("now_utc"),
                    "total_fetched": diag.get("total_transactions_fetched", 0),
                    "upcoming_count": diag.get("upcoming_count", 0),
                    "in_progress_count": diag.get("in_progress_count", 0),
                    "past_count": diag.get("past_count", 0),
                    "unknown_dates_count": diag.get("unknown_dates_count", 0),
                    "pages_fetched": len(diag.get("pages", [])),
                }

        return attrs


# =============================================================================
# NEXT BOOKING SENSORS
# =============================================================================


class NextBookingStartSensor(LocalTrailerHireBaseSensor):
    """Sensor for next booking start time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-start"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, SENSOR_NEXT_START, "Next Booking Start")

    @property
    def native_value(self) -> datetime | None:
        """Return the next booking start time (from upcoming only)."""
        booking = self._next_upcoming_booking
        if not booking:
            return None
        return parse_iso_datetime(booking.get("booking_start"))

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes for the next booking."""
        booking = self._next_upcoming_booking
        if not booking:
            return {"has_booking": False, "upcoming_count": 0}

        return {
            "has_booking": True,
            "upcoming_count": len(self._upcoming_bookings),
            "transaction_id": booking.get("transaction_id"),
            "listing_title": booking.get("listing_title"),
            "customer_name": self._format_customer_name(booking),
        }

    @staticmethod
    def _format_customer_name(booking: dict[str, Any]) -> str | None:
        """Format customer name from booking data."""
        first = booking.get("customer_first_name")
        last = booking.get("customer_last_name")
        if first and last:
            return f"{first} {last}"
        elif first:
            return first
        elif booking.get("customer_display_name"):
            return booking["customer_display_name"]
        return None


class NextBookingEndSensor(LocalTrailerHireBaseSensor):
    """Sensor for next booking end time."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-end"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, SENSOR_NEXT_END, "Next Booking End")

    @property
    def native_value(self) -> datetime | None:
        """Return the next booking end time (from upcoming only)."""
        booking = self._next_upcoming_booking
        if not booking:
            return None
        return parse_iso_datetime(booking.get("booking_end"))

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        booking = self._next_upcoming_booking
        if not booking:
            return {"has_booking": False}

        return {
            "has_booking": True,
            "transaction_id": booking.get("transaction_id"),
        }


class NextBookingCustomerSensor(LocalTrailerHireBaseSensor):
    """Sensor for next booking customer name."""

    _attr_icon = "mdi:account"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator, entry, SENSOR_NEXT_CUSTOMER, "Next Booking Customer"
        )

    @property
    def native_value(self) -> str | None:
        """Return the next booking customer name (from upcoming only)."""
        booking = self._next_upcoming_booking
        if not booking:
            return None

        first = booking.get("customer_first_name")
        last = booking.get("customer_last_name")
        if first and last:
            return f"{first} {last}"
        elif first:
            return first
        elif booking.get("customer_display_name"):
            return booking["customer_display_name"]

        return "(Unknown Customer)"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return customer details including structured customer object."""
        booking = self._next_upcoming_booking
        if not booking:
            return {"has_booking": False}

        attrs: dict[str, Any] = {"has_booking": True}

        # Include full structured customer object if present
        customer_obj = booking.get("customer")
        if customer_obj:
            attrs["customer"] = customer_obj

        # Legacy flat attributes for backwards compatibility
        if booking.get("customer_first_name"):
            attrs["first_name"] = booking["customer_first_name"]
        if booking.get("customer_last_name"):
            attrs["last_name"] = booking["customer_last_name"]
        if booking.get("customer_phone"):
            attrs["phone"] = booking["customer_phone"]
        if booking.get("pickup_address"):
            attrs["pickup_address"] = booking["pickup_address"]
        if booking.get("pickup_suburb"):
            attrs["pickup_suburb"] = booking["pickup_suburb"]
        if booking.get("transaction_id"):
            attrs["transaction_id"] = booking["transaction_id"]

        return attrs


class NextBookingPayoutSensor(LocalTrailerHireBaseSensor):
    """Sensor for next booking payout total."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, SENSOR_NEXT_PAYOUT, "Next Booking Payout")

    @property
    def native_value(self) -> float | None:
        """Return the next booking payout total (from upcoming only)."""
        booking = self._next_upcoming_booking
        if not booking:
            return None

        return booking.get("payout_total_aud")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return financial details."""
        booking = self._next_upcoming_booking
        if not booking:
            return {"has_booking": False}

        attrs: dict[str, Any] = {"has_booking": True}

        if booking.get("payin_total_aud") is not None:
            attrs["payin_total"] = booking["payin_total_aud"]
        if booking.get("last_transition"):
            attrs["last_transition"] = booking["last_transition"]
        if booking.get("state"):
            attrs["state"] = booking["state"]
        if booking.get("last_transitioned_at"):
            attrs["last_transitioned_at"] = booking["last_transitioned_at"]
        if booking.get("transaction_id"):
            attrs["transaction_id"] = booking["transaction_id"]

        return attrs


# =============================================================================
# EARNINGS SENSORS
# =============================================================================


class EarningsTotalSensor(LocalTrailerHireBaseSensor):
    """Sensor for total payout across all fetched transactions."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-multiple"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, SENSOR_EARNINGS_TOTAL, "Earnings Total")

    @property
    def native_value(self) -> float:
        """Return the sum of all payout_total_aud where present."""
        total = sum(
            b.get("payout_total_aud", 0) or 0
            for b in self._all_bookings
            if b.get("payout_total_aud") is not None
        )
        return round(total, 2)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return breakdown of earnings."""
        return {
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            "bookings_with_payout": sum(
                1 for b in self._all_bookings if b.get("payout_total_aud") is not None
            ),
        }


class EarningsEarnedSensor(LocalTrailerHireBaseSensor):
    """Sensor for earned payout (past bookings or payout-completed transitions)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-check"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, SENSOR_EARNINGS_EARNED, "Earnings Earned")

    @property
    def native_value(self) -> float:
        """Return sum of payout for past bookings or payout-completed transitions."""
        earned = 0.0
        for booking in self._all_bookings:
            payout = booking.get("payout_total_aud")
            if payout is None:
                continue

            category = booking.get("category")
            last_transition = booking.get("last_transition")

            # Count as earned if:
            # 1. Category is past, OR
            # 2. Last transition indicates payout/complete
            if category == CATEGORY_PAST or last_transition in PAYOUT_TRANSITIONS:
                earned += payout

        return round(earned, 2)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return breakdown."""
        past_count = 0
        payout_transition_count = 0

        for booking in self._all_bookings:
            if booking.get("payout_total_aud") is None:
                continue
            category = booking.get("category")
            last_transition = booking.get("last_transition")

            if category == CATEGORY_PAST:
                past_count += 1
            elif last_transition in PAYOUT_TRANSITIONS:
                payout_transition_count += 1

        return {
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            "past_bookings_count": past_count,
            "payout_transition_count": payout_transition_count,
        }


class EarningsScheduledSensor(LocalTrailerHireBaseSensor):
    """Sensor for scheduled payout (upcoming or in-progress bookings)."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-clock"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator, entry, SENSOR_EARNINGS_SCHEDULED, "Earnings Scheduled"
        )

    @property
    def native_value(self) -> float:
        """Return sum of payout for upcoming or in-progress bookings."""
        scheduled = 0.0
        for booking in self._all_bookings:
            payout = booking.get("payout_total_aud")
            if payout is None:
                continue

            category = booking.get("category")
            if category in (CATEGORY_UPCOMING, CATEGORY_IN_PROGRESS):
                scheduled += payout

        return round(scheduled, 2)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return breakdown."""
        upcoming_payout = sum(
            b.get("payout_total_aud", 0) or 0
            for b in self._upcoming_bookings
            if b.get("payout_total_aud") is not None
        )
        in_progress_payout = sum(
            b.get("payout_total_aud", 0) or 0
            for b in self._in_progress_bookings
            if b.get("payout_total_aud") is not None
        )

        return {
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            "upcoming_payout": round(upcoming_payout, 2),
            "in_progress_payout": round(in_progress_payout, 2),
            "upcoming_count": len(self._upcoming_bookings),
            "in_progress_count": len(self._in_progress_bookings),
        }


class BookingsTotalPayinSensor(LocalTrailerHireBaseSensor):
    """Sensor for total payin (customer payments) across all transactions."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.TOTAL
    _attr_icon = "mdi:cash-plus"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            coordinator, entry, SENSOR_BOOKINGS_TOTAL_PAYIN, "Bookings Total Payin"
        )

    @property
    def native_value(self) -> float:
        """Return the sum of all payin_total_aud where present."""
        total = sum(
            b.get("payin_total_aud", 0) or 0
            for b in self._all_bookings
            if b.get("payin_total_aud") is not None
        )
        return round(total, 2)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return breakdown."""
        return {
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
            "bookings_with_payin": sum(
                1 for b in self._all_bookings if b.get("payin_total_aud") is not None
            ),
        }


# =============================================================================
# PENDING REQUESTS
# =============================================================================


class PendingRequestCountSensor(LocalTrailerHireBaseSensor):
    """Count of bookings whose last_transition is a pending request."""

    _attr_icon = "mdi:bell-alert-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "pending_requests_count", "Pending Requests")

    @property
    def _pending(self) -> list[dict[str, Any]]:
        return [
            b for b in self._all_bookings
            if b.get("last_transition") in REQUEST_TRANSITIONS
        ]

    @property
    def native_value(self) -> int:
        return len(self._pending)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            ATTR_BOOKING_COUNT: len(self._pending),
            ATTR_LAST_UPDATE: datetime.now(timezone.utc).isoformat(),
        }
        if self._include_booking_lists:
            attrs[ATTR_BOOKINGS] = self._pending
        return attrs


# =============================================================================
# EARNINGS BY PERIOD
# =============================================================================


def _payout_in_window(
    bookings: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> float:
    """Sum payout for bookings whose start falls within [window_start, window_end)."""
    total = 0.0
    for booking in bookings:
        payout = booking.get("payout_total_aud")
        if payout is None:
            continue
        start_dt = parse_iso_datetime(booking.get("booking_start"))
        if start_dt is None:
            continue
        if window_start <= start_dt < window_end:
            total += payout
    return round(total, 2)


class _EarningsWindowSensor(LocalTrailerHireBaseSensor):
    """Base for earnings-over-a-rolling-window sensors."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.TOTAL

    def _window(self) -> tuple[datetime, datetime]:
        raise NotImplementedError

    @property
    def native_value(self) -> float:
        start, end = self._window()
        return _payout_in_window(self._all_bookings, start, end)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success


class EarningsLast30DaysSensor(_EarningsWindowSensor):
    """Earnings for bookings starting in the last 30 days."""

    _attr_icon = "mdi:cash-clock"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "earnings_last_30_days_aud", "Earnings Last 30 Days")

    def _window(self) -> tuple[datetime, datetime]:
        from datetime import timedelta as _td  # local import to avoid module-level shuffle
        now = datetime.now(timezone.utc)
        return now - _td(days=30), now + _td(days=1)


class EarningsMonthToDateSensor(_EarningsWindowSensor):
    """Earnings for bookings starting since the 1st of this month."""

    _attr_icon = "mdi:cash-clock"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "earnings_month_to_date_aud", "Earnings Month To Date")

    def _window(self) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta as _td
        return start, now + _td(days=1)


class EarningsYearToDateSensor(_EarningsWindowSensor):
    """Earnings for bookings starting since 1 January of this year."""

    _attr_icon = "mdi:cash-clock"

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "earnings_year_to_date_aud", "Earnings Year To Date")

    def _window(self) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        from datetime import timedelta as _td
        return start, now + _td(days=1)


# =============================================================================
# PER-LISTING SENSORS
# =============================================================================


class _BaseListingSensor(
    CoordinatorEntity[LocalTrailerHireCoordinator], SensorEntity
):
    """Common base for per-listing sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LocalTrailerHireCoordinator,
        entry: ConfigEntry,
        listing_id: str,
        suffix: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._listing_id = listing_id
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_listing_{listing_id}_{suffix}"

    @property
    def _listing(self) -> dict[str, Any] | None:
        for listing in self.coordinator.listings:
            if listing.get("id") == self._listing_id:
                return listing
        return None

    @property
    def device_info(self) -> DeviceInfo:
        listing = self._listing or {}
        return DeviceInfo(
            identifiers={(DOMAIN, f"listing_{self._listing_id}")},
            name=listing.get("title") or "Trailer listing",
            manufacturer="Sharetribe",
            model="Listing",
            via_device=(DOMAIN, self._entry.entry_id),
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._listing is not None


class ListingStateSensor(_BaseListingSensor):
    """Listing state (published / closed / draft / pendingApproval)."""

    _attr_icon = "mdi:flag-variant"

    def __init__(
        self,
        coordinator: LocalTrailerHireCoordinator,
        entry: ConfigEntry,
        listing_id: str,
    ) -> None:
        super().__init__(coordinator, entry, listing_id, "state", "State")

    @property
    def native_value(self) -> str | None:
        listing = self._listing
        return listing.get("state") if listing else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        listing = self._listing or {}
        return {
            "title": listing.get("title"),
            "deleted": listing.get("deleted"),
            "image_url": listing.get("image_url"),
            "listing_id": self._listing_id,
        }


class ListingPriceSensor(_BaseListingSensor):
    """Listing daily price in AUD."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_native_unit_of_measurement = CURRENCY_DOLLAR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash"

    def __init__(
        self,
        coordinator: LocalTrailerHireCoordinator,
        entry: ConfigEntry,
        listing_id: str,
    ) -> None:
        super().__init__(coordinator, entry, listing_id, "price", "Price")

    @property
    def native_value(self) -> float | None:
        listing = self._listing
        return listing.get("price_aud") if listing else None


class ListingBookingsCountSensor(_BaseListingSensor):
    """Count of upcoming + in-progress bookings on a single listing."""

    _attr_icon = "mdi:calendar-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: LocalTrailerHireCoordinator,
        entry: ConfigEntry,
        listing_id: str,
    ) -> None:
        super().__init__(coordinator, entry, listing_id, "bookings_count", "Active Bookings")

    @property
    def native_value(self) -> int:
        bookings = self.coordinator.data or []
        return sum(
            1
            for b in bookings
            if b.get("listing_id") == self._listing_id
            and b.get("category") in (CATEGORY_UPCOMING, CATEGORY_IN_PROGRESS)
        )
