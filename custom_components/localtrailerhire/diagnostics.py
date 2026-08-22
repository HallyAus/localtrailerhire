"""Diagnostics support for Local Trailer Hire."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_CLIENT_ID, CONF_REFRESH_TOKEN, DOMAIN

# Keys to redact from diagnostics output
TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_CLIENT_ID,
    CONF_REFRESH_TOKEN,
    "access_token",
    "refresh_token",
    "customer_phone",
    "customer_first_name",
    "customer_last_name",
    "customer_display_name",
    "pickup_address",
    "pickup_suburb",
    "customerPhoneNumber",
    "phoneNumber",
    "first_name",
    "last_name",
    "display_name",
    "abbreviated_name",
    # Driver licence fields
    "driversLicenceNumber",
    "driversLicenceIssuedBy",
    "driversLicenceExpiryDate",
    "licence_number",
    # Address fields
    "residentialAddress",
    "building",
    "referrer_name",
    "promo_code",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    This provides detailed diagnostic information visible in HA's
    Settings > Devices & Services > Integration > Diagnostics.
    """
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    api = data.get("api")
    coordinator = data.get("coordinator")

    diagnostics: dict[str, Any] = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
    }

    # Add API diagnostics
    if api:
        api_diag = api.diagnostics if hasattr(api, "diagnostics") else {}
        diagnostics["api"] = {
            "last_diagnostics": _redact_sample_transactions(api_diag),
            "has_access_token": api.has_access_token,
            "token_expiry": (api.token_expiry.isoformat() if api.token_expiry else None),
        }

    # Add coordinator diagnostics
    if coordinator:
        diagnostics["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "last_update_time": (
                coordinator.last_update_success_time.isoformat()
                if hasattr(coordinator, "last_update_success_time")
                and coordinator.last_update_success_time
                else None
            ),
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds() if coordinator.update_interval else None
            ),
            "last_transitions_filter": coordinator.last_transitions,
            "include_sensitive_data": getattr(coordinator, "include_sensitive", False),
            "bookings_count": len(coordinator.data) if coordinator.data else 0,
            "customer_history_count": len(getattr(coordinator, "customer_history", {})),
            "message_history_conversation_count": len(getattr(coordinator, "message_history", {})),
            "message_history_message_count": sum(
                len(record.get("messages", {}))
                for record in getattr(coordinator, "message_history", {}).values()
            ),
            "history_retention": getattr(coordinator, "history_retention", None),
            "archive_messages": getattr(coordinator, "archive_messages", False),
            "auto_review": getattr(coordinator, "auto_review_status", {}),
        }

        # Add sample of bookings (redacted)
        if coordinator.data:
            diagnostics["bookings_sample"] = [
                _redact_booking(booking) for booking in coordinator.data[:5]
            ]

    return diagnostics


def _redact_sample_transactions(diag: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive data from sample transactions in diagnostics."""
    if not diag:
        return {}

    result = dict(diag)

    # Redact sample transactions
    if "sample_transactions" in result:
        result["sample_transactions"] = [
            {k: v for k, v in txn.items() if k not in TO_REDACT}
            for txn in result.get("sample_transactions", [])
        ]

    return result


def _redact_booking(booking: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive data from a booking."""
    redacted = {}
    for key, value in booking.items():
        if key in TO_REDACT or "phone" in key.lower() or "address" in key.lower():
            redacted[key] = "**REDACTED**"
        elif key == "customer" and isinstance(value, dict):
            # Redact nested customer object
            redacted[key] = _redact_customer(value)
        elif key == "booking_details" and isinstance(value, dict):
            redacted[key] = async_redact_data(value, TO_REDACT)
        elif key == "licence" and isinstance(value, dict):
            redacted[key] = "**REDACTED**"
        else:
            redacted[key] = value
    return redacted


def _redact_customer(customer: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive data from customer object."""
    redacted = {}
    for key, value in customer.items():
        if (
            key in TO_REDACT
            or key in ("phone", "licence")
            or (key == "address" and isinstance(value, dict))
        ):
            redacted[key] = "**REDACTED**"
        else:
            redacted[key] = value
    return redacted
