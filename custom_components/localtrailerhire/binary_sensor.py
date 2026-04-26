"""Binary sensor platform for Local Trailer Hire."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LocalTrailerHireCoordinator
from .const import DOMAIN, REQUEST_TRANSITIONS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensors for an entry."""
    coordinator: LocalTrailerHireCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    async_add_entities([PendingActionBinarySensor(coordinator, entry)])


class PendingActionBinarySensor(
    CoordinatorEntity[LocalTrailerHireCoordinator], BinarySensorEntity
):
    """On while one or more bookings are awaiting host accept/decline."""

    _attr_has_entity_name = True
    _attr_name = "Pending Action"
    _attr_icon = "mdi:bell-alert"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        coordinator: LocalTrailerHireCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_pending_action"

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

    def _pending(self) -> list[dict[str, Any]]:
        return [
            booking
            for booking in self.coordinator.data or []
            if booking.get("last_transition") in REQUEST_TRANSITIONS
        ]

    @property
    def is_on(self) -> bool:
        return bool(self._pending())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pending = self._pending()
        return {
            "pending_count": len(pending),
            "transactions": [
                {
                    "transaction_id": p.get("transaction_id"),
                    "listing_title": p.get("listing_title"),
                    "customer": p.get("customer_display_name")
                    or p.get("customer_first_name"),
                    "booking_start": p.get("booking_start"),
                    "booking_end": p.get("booking_end"),
                    "payout_total_aud": p.get("payout_total_aud"),
                }
                for p in pending
            ],
            "last_update": datetime.now(timezone.utc).isoformat(),
        }
