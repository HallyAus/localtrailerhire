"""Constants for the Local Trailer Hire integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "localtrailerhire"

# API endpoints
AUTH_TOKEN_URL: Final = "https://flex-api.sharetribe.com/v1/auth/token"
TRANSACTIONS_URL: Final = "https://flex-api.sharetribe.com/v1/api/transactions/query"

# Default configuration
DEFAULT_SCAN_INTERVAL: Final = 10  # minutes
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 60

# Token refresh buffer (refresh 60 seconds before expiry)
TOKEN_REFRESH_BUFFER: Final = 60

# Pagination
DEFAULT_PER_PAGE: Final = 100

# Default transitions to query (configurable)
DEFAULT_LAST_TRANSITIONS: Final = [
    "transition/accept",
    "transition/complete",
    "transition/confirm-payment",
    "transition/request-payment",
    "transition/request-payment-after-enquiry",
]

# Configuration keys
CONF_CLIENT_ID: Final = "client_id"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_LAST_TRANSITIONS: Final = "last_transitions"

# Sensor names
SENSOR_BOOKINGS: Final = "bookings"
SENSOR_NEXT_START: Final = "next_booking_start"
SENSOR_NEXT_END: Final = "next_booking_end"
SENSOR_NEXT_CUSTOMER: Final = "next_booking_customer"
SENSOR_NEXT_PAYOUT: Final = "next_booking_payout"

# Attributes
ATTR_BOOKINGS: Final = "bookings"
ATTR_BOOKING_COUNT: Final = "booking_count"
ATTR_LAST_UPDATE: Final = "last_update"
