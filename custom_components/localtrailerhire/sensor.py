"""Sensor platform for Local Trailer Hire integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_DOLLAR
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LocalTrailerHireCoordinator
from .const import (
    ATTR_BOOKING_COUNT,
    ATTR_BOOKINGS,
    ATTR_LAST_UPDATE,
    DOMAIN,
    SENSOR_BOOKINGS,
    SENSOR_NEXT_CUSTOMER,
    SENSOR_NEXT_END,
    SENSOR_NEXT_PAYOUT,
    SENSOR_NEXT_START,
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
        BookingsSensor(coordinator, entry),
        NextBookingStartSensor(coordinator, entry),
        NextBookingEndSensor(coordinator, entry),
        NextBookingCustomerSensor(coordinator, entry),
        NextBookingPayoutSensor(coordinator, entry),
    ]

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
    def _next_booking(self) -> dict[str, Any] | None:
        """Get the next booking (first in sorted list)."""
        if self.coordinator.data and len(self.coordinator.data) > 0:
            return self.coordinator.data[0]
        return None


class BookingsSensor(LocalTrailerHireBaseSensor):
    """Sensor for all upcoming bookings."""

    _attr_icon = "mdi:calendar-clock"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: LocalTrailerHireCoordinator, entry: ConfigEntry
    ) -> None:
        """Initialize the bookings sensor."""
        super().__init__(coordinator, entry, SENSOR_BOOKINGS, "Upcoming Bookings")

    @property
    def native_value(self) -> int:
        """Return the number of upcoming bookings."""
        if self.coordinator.data:
            return len(self.coordinator.data)
        return 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return sensor attributes."""
        attrs: dict[str, Any] = {
            ATTR_BOOKING_COUNT: self.native_value,
            ATTR_LAST_UPDATE: datetime.now().isoformat(),
        }

        if self.coordinator.data:
            # Include full bookings list as attribute
            attrs[ATTR_BOOKINGS] = self.coordinator.data

        return attrs


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
        """Return the next booking start time."""
        booking = self._next_booking
        if booking and booking.get("booking_start"):
            try:
                return datetime.fromisoformat(
                    booking["booking_start"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes for the next booking."""
        booking = self._next_booking
        if not booking:
            return {}

        return {
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
        """Return the next booking end time."""
        booking = self._next_booking
        if booking and booking.get("booking_end"):
            try:
                return datetime.fromisoformat(
                    booking["booking_end"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                return None
        return None


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
        """Return the next booking customer name."""
        booking = self._next_booking
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
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return customer details."""
        booking = self._next_booking
        if not booking:
            return {}

        attrs: dict[str, Any] = {}

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
        """Return the next booking payout total."""
        booking = self._next_booking
        if booking:
            return booking.get("payout_total_aud")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return financial details."""
        booking = self._next_booking
        if not booking:
            return {}

        attrs: dict[str, Any] = {}

        if booking.get("payin_total_aud") is not None:
            attrs["payin_total"] = booking["payin_total_aud"]
        if booking.get("last_transition"):
            attrs["last_transition"] = booking["last_transition"]
        if booking.get("state"):
            attrs["state"] = booking["state"]
        if booking.get("last_transitioned_at"):
            attrs["last_transitioned_at"] = booking["last_transitioned_at"]

        return attrs
