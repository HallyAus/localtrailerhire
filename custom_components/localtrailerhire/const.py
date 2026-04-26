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
# Empty list = no filter, fetch ALL transactions and determine upcoming by dates only
# This is the recommended default to avoid missing valid bookings
DEFAULT_LAST_TRANSITIONS: Final = []

# Broad transition list for users who want to filter (optional)
# Includes common booking states - use this if API returns too many irrelevant transactions
BROAD_TRANSITIONS: Final = [
    "transition/accept",
    "transition/complete",
    "transition/confirm-payment",
    "transition/confirm-payment-instant-booking",
    "transition/expire-refundable-period",
    "transition/request-payment",
    "transition/request-payment-after-enquiry",
    "transition/mark-delivered",
    "transition/mark-received",
    "transition/mark-received-from-purchased",
]

# Configuration keys
CONF_CLIENT_ID: Final = "client_id"
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_LAST_TRANSITIONS: Final = "last_transitions"
CONF_INCLUDE_SENSITIVE: Final = "include_sensitive_data"

# Default for sensitive data (OFF for privacy)
DEFAULT_INCLUDE_SENSITIVE: Final = False

# Default for including booking list attributes (ON by default)
CONF_INCLUDE_BOOKING_LISTS: Final = "include_booking_lists"
DEFAULT_INCLUDE_BOOKING_LISTS: Final = True

# Sensor names - Count sensors
SENSOR_UPCOMING_COUNT: Final = "upcoming_bookings_count"
SENSOR_IN_PROGRESS_COUNT: Final = "in_progress_bookings_count"
SENSOR_UNKNOWN_DATES_COUNT: Final = "unknown_dates_count"
SENSOR_TOTAL_COUNT: Final = "total_bookings_count"

# Sensor names - Next booking sensors
SENSOR_NEXT_START: Final = "next_booking_start"
SENSOR_NEXT_END: Final = "next_booking_end"
SENSOR_NEXT_CUSTOMER: Final = "next_booking_customer"
SENSOR_NEXT_PAYOUT: Final = "next_booking_payout"

# Sensor names - Earnings sensors
SENSOR_EARNINGS_TOTAL: Final = "earnings_total_aud"
SENSOR_EARNINGS_EARNED: Final = "earnings_earned_aud"
SENSOR_EARNINGS_SCHEDULED: Final = "earnings_scheduled_aud"
SENSOR_BOOKINGS_TOTAL_PAYIN: Final = "bookings_total_payin_aud"

# Booking categories
CATEGORY_UPCOMING: Final = "upcoming"
CATEGORY_IN_PROGRESS: Final = "in_progress"
CATEGORY_PAST: Final = "past"
CATEGORY_UNKNOWN: Final = "unknown"

# Transitions that indicate earned/completed payout
PAYOUT_TRANSITIONS: Final = [
    "transition/complete",
    "transition/review-1-by-customer",
    "transition/review-1-by-provider",
    "transition/review-2-by-customer",
    "transition/review-2-by-provider",
    "transition/expire-review-period",
    "transition/expire-customer-review-period",
    "transition/expire-provider-review-period",
]

# Attributes
ATTR_BOOKINGS: Final = "bookings"
ATTR_BOOKING_COUNT: Final = "booking_count"
ATTR_LAST_UPDATE: Final = "last_update"
ATTR_BREAKDOWN: Final = "breakdown"

# Message API endpoint
MESSAGE_SEND_URL: Final = "https://flex-api.sharetribe.com/v1/api/messages/send"

# Transitions that indicate a confirmed booking
# These are the transitions where a booking has been confirmed/accepted
CONFIRMED_TRANSITIONS: Final = frozenset([
    "transition/confirm-payment",
    "transition/confirm-payment-instant-booking",
    "transition/confirm-payment-instant-book",  # Alternative naming
    "transition/expire-refundable-period",
    "transition/accept",
    "transition/change-accepted-booking",
    "transition/change-non-refundable-booking",
])

# Maximum pages to fetch (safety cap)
MAX_PAGES: Final = 50

# Service names
SERVICE_SEND_MESSAGE: Final = "send_message"
SERVICE_REFRESH_NOW: Final = "refresh_now"
SERVICE_FIRE_CONFIRMED_EVENTS: Final = "fire_confirmed_events"
SERVICE_MARK_MESSAGE_SENT: Final = "mark_message_sent"

# Event names
EVENT_BOOKING_CONFIRMED: Final = "localtrailerhire_booking_confirmed"
EVENT_MESSAGE_SENT: Final = "localtrailerhire_message_sent"

# Storage keys
STORAGE_KEY: Final = "localtrailerhire_data"
STORAGE_VERSION: Final = 2
