# Local Trailer Hire - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/HallyAus/localtrailerhire.svg)](https://github.com/HallyAus/localtrailerhire/releases)
[![License](https://img.shields.io/github/license/HallyAus/localtrailerhire.svg)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow.svg)](https://www.buymeacoffee.com/printforge)

A custom Home Assistant integration for [LocalTrailerHire](https://localtrailerhire.com.au) (Sharetribe Flex marketplace) that displays booking information as sensors.

## Features

- **Booking Count Sensors**: Separate sensors for upcoming, in-progress, unknown dates, and total bookings
- **Next Booking Sensors**: Start time, end time, customer name, and payout for the next upcoming booking
- **Earnings Sensors**: Track total earnings, earned (completed) and scheduled (future) payouts
- **Automatic Token Refresh**: Handles OAuth2 token refresh automatically
- **Configurable Update Interval**: Set how often to fetch new data (default: 10 minutes)
- **Send Message Service**: Send messages to customers through the marketplace
- **Booking Confirmed Events**: Fire Home Assistant events when bookings are confirmed
- **Privacy Controls**: Option to mask sensitive customer data

## Booking Categories

Bookings are categorized based on their dates relative to the current time (UTC):

| Category | Definition |
|----------|------------|
| **Upcoming** | `booking_start >= now` (future bookings that haven't started) |
| **In Progress** | `booking_start <= now < booking_end` (currently active bookings) |
| **Past** | `booking_end < now` (completed bookings) |
| **Unknown** | Missing `booking_start` or `booking_end` dates |

## Installation

### Manual Installation

1. Copy the `custom_components/localtrailerhire` folder to your Home Assistant `custom_components` directory:

   ```bash
   # From your Home Assistant config directory
   mkdir -p custom_components
   cp -r /path/to/localtrailerhire/custom_components/localtrailerhire custom_components/
   ```

2. Restart Home Assistant

3. Go to **Settings** > **Devices & Services** > **Add Integration**

4. Search for "Local Trailer Hire" and follow the configuration flow

### HACS Installation (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance

2. Add this repository as a custom repository in HACS:
   - Open HACS in Home Assistant
   - Click on **Integrations**
   - Click the three dots menu (top right) and select **Custom repositories**
   - Add the repository URL: `https://github.com/HallyAus/localtrailerhire`
   - Select category: **Integration**
   - Click **Add**

3. Search for "Local Trailer Hire" in HACS and click **Download**

4. Restart Home Assistant

5. Go to **Settings** > **Devices & Services** > **Add Integration**

6. Search for "Local Trailer Hire" and follow the configuration flow

#### One-Click Install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HallyAus&repository=localtrailerhire&category=integration)

## Configuration

### Required Credentials

You'll need the following from your Sharetribe Flex marketplace:

- **Client ID**: Your Sharetribe Flex application client ID
- **Username**: Your marketplace account email (optional if using refresh token)
- **Password**: Your marketplace account password (optional if using refresh token)
- **Refresh Token**: Alternative to username/password for token-based authentication

### Getting Your Client ID

1. Log in to [Sharetribe Console](https://flex-console.sharetribe.com/)
2. Go to **Build** > **Applications**
3. Create or select an application
4. Copy the Client ID

### Options

- **Update Interval**: How often to fetch booking data (1-60 minutes, default: 10)
- **Transaction Transitions**: Leave empty to fetch all transactions (recommended)
- **Include Sensitive Data**: Show full driver licence and unmasked phone numbers
- **Include Booking Lists**: Include full booking lists in sensor attributes (can be disabled to reduce state size)

## Sensors

### Count Sensors

#### `sensor.local_trailer_hire_upcoming_bookings`

Count of upcoming bookings (where `booking_start >= now`).

**Attributes:**
- `bookings`: List of upcoming bookings (if enabled)
- `booking_count`: Number of upcoming bookings
- `last_update`: Timestamp of last data refresh

#### `sensor.local_trailer_hire_in_progress_bookings`

Count of in-progress bookings (where `booking_start <= now < booking_end`).

**Attributes:**
- `bookings`: List of in-progress bookings (if enabled)
- `booking_count`: Number of in-progress bookings
- `last_update`: Timestamp of last data refresh

#### `sensor.local_trailer_hire_unknown_dates_bookings`

Count of bookings with missing date information.

**Attributes:**
- `bookings`: List of bookings with unknown dates (if enabled)
- `booking_count`: Number of unknown date bookings
- `last_update`: Timestamp of last data refresh

#### `sensor.local_trailer_hire_total_bookings`

Total count of all fetched bookings across all categories.

**Attributes:**
- `breakdown`: Object with counts for each category (upcoming, in_progress, past, unknown_dates)
- `_diagnostics`: Debugging information from the API

### Next Booking Sensors

These sensors show information about the **next upcoming booking** (the soonest booking where `booking_start >= now`).

#### `sensor.local_trailer_hire_next_booking_start`

The start time of the next upcoming booking (timestamp).

**Attributes:**
- `has_booking`: Boolean indicating if there's an upcoming booking
- `upcoming_count`: Total count of upcoming bookings
- `transaction_id`: The booking transaction ID
- `listing_title`: The listing/trailer name
- `customer_name`: Customer's full name

#### `sensor.local_trailer_hire_next_booking_end`

The end time of the next upcoming booking (timestamp).

#### `sensor.local_trailer_hire_next_booking_customer`

The customer name for the next upcoming booking.

**Attributes:**
- `customer`: Structured customer object with nested data
- `first_name`: Customer's first name
- `last_name`: Customer's last name
- `phone`: Customer's phone number (masked if sensitive data disabled)
- `pickup_address`: Pickup address (if available)
- `pickup_suburb`: Pickup suburb (if available)

#### `sensor.local_trailer_hire_next_booking_payout`

The payout amount for the next upcoming booking (in AUD).

**Attributes:**
- `payin_total`: Total amount paid by customer
- `last_transition`: Last transaction state transition
- `state`: Current booking state
- `last_transitioned_at`: Timestamp of last state change

### Earnings Sensors

#### `sensor.local_trailer_hire_earnings_total`

Total payout across all fetched transactions (in AUD).

#### `sensor.local_trailer_hire_earnings_earned`

Payout from completed bookings (past bookings or those with payout-completed transitions).

**Attributes:**
- `past_bookings_count`: Number of past bookings with payout
- `payout_transition_count`: Number of bookings with payout transitions

#### `sensor.local_trailer_hire_earnings_scheduled`

Payout from upcoming and in-progress bookings (in AUD).

**Attributes:**
- `upcoming_payout`: Payout from upcoming bookings
- `in_progress_payout`: Payout from in-progress bookings
- `upcoming_count`: Number of upcoming bookings
- `in_progress_count`: Number of in-progress bookings

#### `sensor.local_trailer_hire_bookings_total_payin`

Total customer payments (payin) across all transactions (in AUD).

## Example Booking Data Structure

Each booking in the `bookings` attribute list contains:

```json
{
  "transaction_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "booking_start": "2024-01-15T00:00:00.000Z",
  "booking_end": "2024-01-17T00:00:00.000Z",
  "category": "upcoming",
  "dates_known": true,
  "customer_first_name": "John",
  "customer_last_name": "Smith",
  "customer_display_name": "John S",
  "customer_phone": "0412****78",
  "customer": {
    "first_name": "John",
    "last_name": "Smith",
    "phone": "0412****78",
    "address": {
      "building": "Unit 5",
      "full": "Unit 5, 123 Main St, Sydney NSW 2000"
    }
  },
  "pickup_address": "123 Main St",
  "pickup_suburb": "Sydney",
  "payout_total_aud": 150.00,
  "payin_total_aud": 180.00,
  "last_transition": "transition/confirm-payment",
  "state": "accepted",
  "last_transitioned_at": "2024-01-14T10:30:00.000Z",
  "listing_title": "6x4 Cage Trailer",
  "listing_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

## Example Automations

### Notify when a new booking is confirmed

```yaml
automation:
  - alias: "New Booking Notification"
    trigger:
      - platform: state
        entity_id: sensor.local_trailer_hire_upcoming_bookings
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state | int > trigger.from_state.state | int }}"
    action:
      - service: notify.mobile_app
        data:
          title: "New Booking!"
          message: >
            New booking from {{ state_attr('sensor.local_trailer_hire_next_booking_start', 'customer_name') }}
            starting {{ states('sensor.local_trailer_hire_next_booking_start') }}
```

### Reminder before pickup

```yaml
automation:
  - alias: "Booking Reminder"
    trigger:
      - platform: time
        at: "08:00:00"
    condition:
      - condition: template
        value_template: >
          {% set next_start = states('sensor.local_trailer_hire_next_booking_start') %}
          {% if next_start not in ['unknown', 'unavailable'] %}
            {{ as_timestamp(next_start) - as_timestamp(now()) < 86400 }}
          {% else %}
            false
          {% endif %}
    action:
      - service: notify.mobile_app
        data:
          title: "Booking Today!"
          message: >
            Trailer pickup today for {{ state_attr('sensor.local_trailer_hire_next_booking_customer', 'first_name') }}
```

### Auto-message customer on booking confirmation

This automation sends an automatic welcome message to customers when their booking is confirmed:

```yaml
automation:
  - alias: "Auto-message on Booking Confirmation"
    description: "Send a welcome message when a booking is confirmed"
    trigger:
      - platform: event
        event_type: localtrailerhire_booking_confirmed
    action:
      - service: localtrailerhire.send_message
        data:
          transaction_id: "{{ trigger.event.data.transaction_id }}"
          message: >
            Hi {{ trigger.event.data.customer_first_name }},

            Thank you for booking the {{ trigger.event.data.listing_title }}!

            Your booking is confirmed for pickup. Please remember to bring:
            - Valid driver's licence
            - The payment card used for the booking

            If you have any questions, please don't hesitate to reach out.

            See you soon!
      - service: notify.mobile_app
        data:
          title: "Auto-message sent"
          message: >
            Welcome message sent to {{ trigger.event.data.customer_first_name }}
            for {{ trigger.event.data.listing_title }}
```

## Services

### `localtrailerhire.send_message`

Send a message to a customer for a specific booking transaction.

**Parameters:**
- `transaction_id` (required): The UUID of the transaction
- `message` (required): The message content to send

**Example:**
```yaml
service: localtrailerhire.send_message
data:
  transaction_id: "12345678-1234-1234-1234-123456789abc"
  message: "Thank you for your booking! Your trailer is ready for pickup."
```

## Events

### `localtrailerhire_booking_confirmed`

Fired when a booking transitions to a confirmed state (payment confirmed, instant booking, or refund period expired) and the booking start date is in the future.

**Event Data:**
- `transaction_id`: The booking transaction ID
- `last_transition`: The transition that triggered this event
- `customer_first_name`: Customer's first name
- `customer_last_name`: Customer's last name
- `customer_display_name`: Customer's display name
- `listing_title`: The listing/trailer name
- `listing_id`: The listing UUID
- `booking_start`: Booking start timestamp
- `booking_end`: Booking end timestamp
- `payout_total_aud`: Payout amount in AUD
- `timestamp`: When the event was fired

### `localtrailerhire_message_sent`

Fired when a message is successfully sent via the `send_message` service.

**Event Data:**
- `transaction_id`: The transaction the message was sent to
- `timestamp`: When the message was sent

## Troubleshooting

### Authentication Issues

- Verify your Client ID is correct
- If using password auth, ensure your email and password are correct
- Check Home Assistant logs for detailed error messages

### No Data Appearing

- Verify you have bookings in your marketplace
- Check the diagnostics attribute on the Total Bookings sensor for API response details
- Review Home Assistant logs for API errors

### Incorrect Booking Counts

The integration categorizes bookings by comparing dates to the current UTC time:
- **Upcoming**: `booking_start >= now` (future start)
- **In Progress**: `booking_start <= now < booking_end` (started but not ended)
- **Past**: `booking_end < now` (already ended)
- **Unknown**: Missing date fields

Check the `_diagnostics` attribute on the Total Bookings sensor to see the `now_utc` timestamp used for categorization.

### Rate Limiting

The integration handles rate limiting automatically with exponential backoff. If you see rate limit warnings, consider increasing the update interval.

## API Details

This integration uses the Sharetribe Flex Marketplace API:

- **Auth Endpoint**: `POST https://flex-api.sharetribe.com/v1/auth/token`
- **Transactions Endpoint**: `GET https://flex-api.sharetribe.com/v1/api/transactions/query`
- **Messages Endpoint**: `POST https://flex-api.sharetribe.com/v1/api/messages/send`

The integration requests JSON responses (`Accept: application/json`) to avoid Transit encoding.

## Security

- Credentials are stored securely in Home Assistant's config entry storage
- Tokens are never logged
- Refresh tokens are automatically renewed and stored
- Password credentials are only used when refresh token is unavailable
- Sensitive customer data (licence, phone) can be masked via options

## License

MIT License

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.
