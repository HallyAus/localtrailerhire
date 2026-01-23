# Local Trailer Hire - Home Assistant Integration

A custom Home Assistant integration for [LocalTrailerHire](https://localtrailerhire.com.au) (Sharetribe Flex marketplace) that displays upcoming bookings as sensors.

## Features

- **Upcoming Bookings Sensor**: Shows the count of all upcoming bookings with full booking list as an attribute
- **Next Booking Sensors**: Individual sensors for:
  - Next booking start time
  - Next booking end time
  - Next booking customer name
  - Next booking payout total
- **Automatic Token Refresh**: Handles OAuth2 token refresh automatically
- **Configurable Update Interval**: Set how often to fetch new data (default: 10 minutes)
- **Configurable Transaction Filters**: Filter bookings by transaction state

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

### HACS Installation (Future)

This integration may be added to HACS in the future.

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
- **Transaction Transitions**: Comma-separated list of transaction transitions to include

Default transitions:
```
transition/accept,transition/complete,transition/confirm-payment,transition/request-payment,transition/request-payment-after-enquiry
```

## Sensors

### `sensor.local_trailer_hire_upcoming_bookings`

Shows the count of upcoming bookings.

**Attributes:**
- `bookings`: List of all upcoming bookings (see structure below)
- `booking_count`: Number of upcoming bookings
- `last_update`: Timestamp of last data refresh

### `sensor.local_trailer_hire_next_booking_start`

The start time of the next booking (timestamp).

**Attributes:**
- `transaction_id`: The booking transaction ID
- `listing_title`: The listing/trailer name
- `customer_name`: Customer's full name

### `sensor.local_trailer_hire_next_booking_end`

The end time of the next booking (timestamp).

### `sensor.local_trailer_hire_next_booking_customer`

The customer name for the next booking.

**Attributes:**
- `first_name`: Customer's first name
- `last_name`: Customer's last name
- `phone`: Customer's phone number (if available)
- `pickup_address`: Pickup address (if available)
- `pickup_suburb`: Pickup suburb (if available)

### `sensor.local_trailer_hire_next_booking_payout`

The payout amount for the next booking (in AUD).

**Attributes:**
- `payin_total`: Total amount paid by customer
- `last_transition`: Last transaction state transition
- `state`: Current booking state
- `last_transitioned_at`: Timestamp of last state change

## Example Booking Data Structure

Each booking in the `bookings` attribute list contains:

```json
{
  "transaction_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "booking_start": "2024-01-15T00:00:00.000Z",
  "booking_end": "2024-01-17T00:00:00.000Z",
  "customer_first_name": "John",
  "customer_last_name": "Smith",
  "customer_display_name": "John S",
  "customer_phone": "0412345678",
  "pickup_address": "123 Main St",
  "pickup_suburb": "Sydney",
  "payout_total_aud": 150.00,
  "payin_total_aud": 180.00,
  "last_transition": "transition/complete",
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

## Troubleshooting

### Authentication Issues

- Verify your Client ID is correct
- If using password auth, ensure your email and password are correct
- Check Home Assistant logs for detailed error messages

### No Data Appearing

- Verify you have upcoming bookings in your marketplace
- Check the transaction transitions filter matches your booking states
- Review Home Assistant logs for API errors

### Rate Limiting

The integration handles rate limiting automatically with exponential backoff. If you see rate limit warnings, consider increasing the update interval.

## API Details

This integration uses the Sharetribe Flex Marketplace API:

- **Auth Endpoint**: `POST https://flex-api.sharetribe.com/v1/auth/token`
- **Transactions Endpoint**: `GET https://flex-api.sharetribe.com/v1/api/transactions/query`

The integration requests JSON responses (`Accept: application/json`) to avoid Transit encoding.

## Security

- Credentials are stored securely in Home Assistant's config entry storage
- Tokens are never logged
- Refresh tokens are automatically renewed and stored
- Password credentials are only used when refresh token is unavailable

## License

MIT License

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.
