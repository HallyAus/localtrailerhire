"""Calendar platform for Local Trailer Hire.

Exposes every fetched booking (upcoming, in-progress, past) as a native
Home Assistant calendar event so users get a real calendar card on their
dashboard rather than digging through sensor attributes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LocalTrailerHireCoordinator
from .const import DOMAIN
from .util import parse_iso_datetime


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calendar entity for an entry."""
    coordinator: LocalTrailerHireCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([LocalTrailerHireCalendar(coordinator, entry)])


class LocalTrailerHireCalendar(
    CoordinatorEntity[LocalTrailerHireCoordinator], CalendarEntity
):
    """Calendar entity that surfaces bookings as calendar events."""

    _attr_has_entity_name = True
    _attr_name = "Bookings"
    _attr_icon = "mdi:calendar-multiple"

    def __init__(
        self,
        coordinator: LocalTrailerHireCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Local Trailer Hire",
            manufacturer="Sharetribe",
            model="Flex Marketplace",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next booking.

        ``CalendarEntity.event`` should reflect what is happening now or
        the next thing on the calendar. Sorting candidates ascending by
        start handles both cases: an in-progress booking has a past start
        and naturally sorts before any future one.
        """
        now = datetime.now(timezone.utc)
        candidates: list[CalendarEvent] = []
        for booking in self.coordinator.data or []:
            event = self._booking_to_event(booking)
            if event is None or event.end <= now:
                continue
            candidates.append(event)

        if not candidates:
            return None

        candidates.sort(key=lambda e: e.start)
        return candidates[0]

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events overlapping the requested window."""
        events: list[CalendarEvent] = []
        for booking in self.coordinator.data or []:
            event = self._booking_to_event(booking)
            if event is None:
                continue
            # Overlap: event ends after window start AND starts before window end
            if event.end <= start_date or event.start >= end_date:
                continue
            events.append(event)
        events.sort(key=lambda e: e.start)
        return events

    @staticmethod
    def _booking_to_event(booking: dict[str, Any]) -> CalendarEvent | None:
        """Convert one booking dict to a CalendarEvent, or None if undatable."""
        start = parse_iso_datetime(booking.get("booking_start"))
        end = parse_iso_datetime(booking.get("booking_end"))
        if start is None or end is None:
            return None

        listing = booking.get("listing_title") or "Trailer"
        customer = (
            booking.get("customer_display_name")
            or booking.get("customer_first_name")
            or "Customer"
        )

        description_parts: list[str] = []
        if txn_id := booking.get("transaction_id"):
            description_parts.append(f"Transaction: {txn_id}")
        if last_transition := booking.get("last_transition"):
            description_parts.append(f"State: {last_transition}")
        if (payout := booking.get("payout_total_aud")) is not None:
            description_parts.append(f"Payout: ${payout:.2f} AUD")
        if pickup := booking.get("pickup_suburb"):
            description_parts.append(f"Pickup: {pickup}")

        return CalendarEvent(
            start=start,
            end=end,
            summary=f"{listing} — {customer}",
            description="\n".join(description_parts) or None,
            uid=booking.get("transaction_id"),
        )
