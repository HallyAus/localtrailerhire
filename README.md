# Local Trailer Hire - Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/release/HallyAus/localtrailerhire.svg)](https://github.com/HallyAus/localtrailerhire/releases)
[![License](https://img.shields.io/github/license/HallyAus/localtrailerhire.svg)](LICENSE)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow.svg)](https://www.buymeacoffee.com/printforge)

A custom Home Assistant integration for [LocalTrailerHire](https://localtrailerhire.com.au) (Sharetribe Flex marketplace) that displays booking information as sensors.

---

## 💚 Support this project — it's my only income from it

If this integration saves you time chasing bookings or messages, please use one of the referrals below. Both you and I get credit. This project is maintained in my spare time and referrals are the only thing funding ongoing development.

### ⭐ Star this repo
[**⭐ Star on GitHub**](https://github.com/HallyAus/localtrailerhire) — takes two seconds and surfaces the project to other LocalTrailerHire hosts.

### 🎁 OVO Energy referral — $120–$180 credit
Pair this with the [OVO Energy Australia HA integration](https://github.com/HallyAus/OVO_Aus_api) and track the energy cost of running your trailer-hire business too. Not an OVO customer yet?

**👉 [www.ovoenergy.com.au/refer/daniel16485](https://www.ovoenergy.com.au/refer/daniel16485)**

- ✅ **$120 credit** paid over 12 months on standard plans
- ✅ **$180 credit** paid over 12 months if you choose The EV Plan
- ✅ Both you and I receive the credit — win-win

### 🛰️ Starlink referral — 1 month free
Storing your trailers somewhere rural or running HA off a remote shed? Starlink gets you online anywhere with a clear view of sky.

**👉 [starlink.com/residential?referral=RC-2455784-77014-69](https://starlink.com/residential?referral=RC-2455784-77014-69&app_source=share)**

- ✅ One free month of Starlink service
- ✅ Works anywhere in AU — bush blocks, farms, sheds out the back

---

## Features

- **Booking Count Sensors**: Separate sensors for upcoming, in-progress, pending requests, unknown dates, and total bookings
- **Next Booking Sensors**: Start time, end time, customer name, and payout for the next upcoming booking
- **Earnings Sensors**: Total, earned, scheduled, MTD, YTD, and last-30-day payouts
- **Reputation Sensors** *(v1.3.0)*: Your average **Rating** and **Review Count** from customer reviews
- **Performance Sensors** *(v1.4.0)*: **Acceptance Rate**, **Response Rate**, and a **Profile** sensor (display name + payouts-enabled), from your booking stats
- **Message Reading** *(v1.4.0)*: **Awaiting Replies** sensor flags active bookings whose latest message is from the customer (you can now *see* replies, not just send them)
- **Native Auto-Review** *(v1.3.0, opt-in)*: Automatically posts a provider review once a booking becomes reviewable — durable across restarts, never double-posts
- **Calendar Entity**: Native Home Assistant calendar exposing every booking as an event
- **Per-Listing Devices**: Each of your trailer listings becomes its own HA device with state, daily price, active-booking count, and a "view on site" link
- **Pending Action Binary Sensor**: Lights up when one or more booking requests need accept/decline
- **Accept / Decline Services**: Approve or reject booking requests directly from automations
- **Send Message & Leave Review Services**: Message customers and post reviews through the marketplace
- **Booking Lifecycle Events**: Fires `booking_request_received`, `booking_confirmed`, `message_sent`, and `review_left` events
- **Automatic Token Refresh**: Handles OAuth2 token refresh automatically
- **Configurable Update Interval**: Set how often to fetch new data (default: 10 minutes)
- **Privacy Controls**: Option to mask sensitive customer data
- **Sample Dashboard**: A ready-to-paste Lovelace dashboard in `dashboards/local_trailer_hire.yaml`

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

Just two things — the same email and password you log in with on
[localtrailerhire.com.au](https://localtrailerhire.com.au):

- **Email**: Your LocalTrailerHire account email
- **Password**: Your LocalTrailerHire account password

That's it. The integration handles the marketplace client ID and OAuth
token refresh automatically. If you'd rather not store your password,
you can paste a refresh token instead — but for most people email +
password is the easiest path.

### Options

- **Update Interval**: How often to fetch booking data (1-60 minutes, default: 10)
- **Transaction Transitions**: Leave empty to fetch all transactions (recommended)
- **Include Sensitive Data**: Show full driver licence and unmasked phone numbers
- **Include Booking Lists**: Include full booking lists in sensor attributes (can be disabled to reduce state size)
- **Auto-leave a review after each booking** *(v1.3.0)*: When enabled, automatically posts a provider review once a past booking becomes reviewable. **Off by default.** See [Auto-Review](#auto-review) below.
- **Auto-review rating** *(v1.3.0)*: Star rating to post automatically (default: 5)
- **Auto-review text** *(v1.3.0)*: The review text to post automatically

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

### Reputation Sensors *(v1.3.0)*

#### `sensor.local_trailer_hire_rating`

Your average star rating across public customer reviews of you as a provider.
`unknown` until you have at least one review.

**Attributes:**
- `review_count`: Number of public reviews
- `recent_reviews`: The 5 most recent reviews (`rating`, `content`, `created_at`)
- `last_update`: Timestamp of last data refresh

#### `sensor.local_trailer_hire_review_count`

Number of public customer reviews of you as a provider.

### Performance & Profile Sensors *(v1.4.0)*

Sourced from your marketplace booking stats (latest full year).

#### `sensor.local_trailer_hire_acceptance_rate`

Your booking acceptance rate as a percentage.

#### `sensor.local_trailer_hire_response_rate`

Your message response rate as a percentage.

#### `sensor.local_trailer_hire_profile`

Your provider display name.

**Attributes:**
- `payouts_enabled` / `charges_enabled`: Stripe payout/charge status
- `stats`: Latest-year stats (acceptance rate, response rate, bookings, hires, missed earnings)
- `last_update`: Timestamp of last data refresh

### Message Sensor *(v1.4.0)*

#### `sensor.local_trailer_hire_awaiting_replies`

Count of **active** bookings (upcoming/in-progress) whose most recent message
came from the customer — i.e. you haven't replied yet. To keep API calls
bounded, up to 25 active bookings are scanned per refresh. (Approximation — the
marketplace API has no per-message "read" flag.)

**Attributes:**
- `transaction_ids`: The transactions awaiting your reply
- `latest_message`: The newest message across the scanned bookings (`content`, `sender_id`, `transaction_id`, `listing_title`)
- `last_update`: Timestamp of last data refresh

## Calendar

### `calendar.local_trailer_hire_bookings`

A native calendar entity that surfaces every fetched booking as a calendar
event, with the listing name and customer in the summary. Use the
**Calendar** card on a dashboard to see the booking schedule at a glance,
or trigger automations on `calendar` start/end events.

Each event includes:
- `summary`: `<listing> — <customer>` (e.g. "6x4 Cage Trailer — Jane S")
- `start` / `end`: booking start and end times
- `description`: transaction ID, last transition, payout, pickup suburb
- `uid`: the transaction ID (so events deduplicate across refreshes)

Bookings with missing dates are omitted.

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

All services accept an optional `config_entry_id` to target a specific
configured entry. It is required only if you have multiple Local Trailer Hire
integrations configured.

### `localtrailerhire.send_message`

Send a message to a customer for a specific booking transaction.

**Parameters:**
- `transaction_id` (required): The UUID of the transaction
- `message` (required): The message content to send
- `config_entry_id` (optional): Target a specific config entry

**Example:**
```yaml
service: localtrailerhire.send_message
data:
  transaction_id: "12345678-1234-1234-1234-123456789abc"
  message: "Thank you for your booking! Your trailer is ready for pickup."
```

### `localtrailerhire.refresh_now`

Force an immediate refresh of booking data from the API. With no parameters,
refreshes every configured entry.

**Parameters:**
- `config_entry_id` (optional): Target a specific config entry

### `localtrailerhire.mark_message_sent`

Manually mark a transaction as having had a confirmation message sent. Use this
to prevent duplicate messages after manual intervention or a misfired
automation.

**Parameters:**
- `transaction_id` (required): The UUID of the transaction
- `config_entry_id` (optional): Target a specific config entry

### `localtrailerhire.fire_confirmed_events`

Re-scan and fire `localtrailerhire_booking_confirmed` events for bookings
transitioned in the last N hours. Useful when debugging automations without
sending real customer messages.

**Parameters:**
- `hours_back` (optional, default `24`, max `168`): How far back to look
- `config_entry_id` (optional): Target a specific config entry

### `localtrailerhire.accept_booking`

Accept a pending booking request. Calls `transition/accept` on the Sharetribe
transaction; the booking moves to confirmed and the customer is charged.

**Parameters:**
- `transaction_id` (required): The UUID of the booking transaction
- `config_entry_id` (optional): Target a specific config entry

**Example:**
```yaml
service: localtrailerhire.accept_booking
data:
  transaction_id: "{{ trigger.event.data.transaction_id }}"
```

### `localtrailerhire.decline_booking`

Decline a pending booking request. Calls `transition/decline` on the
Sharetribe transaction.

**Parameters:**
- `transaction_id` (required): The UUID of the booking transaction
- `config_entry_id` (optional): Target a specific config entry

### `localtrailerhire.leave_review`

Post a provider review on a completed booking. By default tries
`transition/review-1-by-provider` (provider goes first); falls back to
`transition/review-2-by-provider` if Sharetribe rejects it (typically
because the customer has already reviewed).

**Parameters:**
- `transaction_id` (required): The UUID of the booking transaction
- `rating` (optional, default `5`): Star rating from 1 to 5
- `review_content` (optional): The review text. A friendly default is used if omitted.
- `transition` (optional): Force `transition/review-1-by-provider` or
  `transition/review-2-by-provider`. Leave empty for auto-select.
- `config_entry_id` (optional): Target a specific config entry

Fires the `localtrailerhire_review_left` event on success. Use this service for
manual or one-off reviews. For hands-off reviews, use the built-in
**[Auto-Review](#auto-review)** option instead of a `delay`-based automation.

## Auto-Review

*(v1.3.0)* The integration can post a provider review for you automatically —
reliably, with no automation YAML.

**Enable it:** Settings → Devices & Services → **Local Trailer Hire** →
**Configure** → tick **"Auto-leave a review after each booking"** (set the
rating and text there too). It is **off by default**.

**How it works:** on each refresh the integration finds past bookings that are
now reviewable and not yet reviewed, posts the review (trying
`review-1-by-provider`, falling back to `review-2-by-provider`), and records it
so it never posts twice. Because that state is persisted, it **survives Home
Assistant restarts** — unlike a `delay`-based automation, which silently drops
the pending review if HA restarts during the (often multi-day) wait between
confirmation and the booking ending. Bookings whose review window has already
closed are skipped. Each auto-review fires `localtrailerhire_review_left` (with
`"auto": true`).

**Is it armed?** Check the **`sensor.local_trailer_hire_auto_review`** diagnostic
sensor (`enabled` / `disabled`). Its attributes show how many bookings have been
auto-reviewed, the **last auto-review time and transaction**, and how many are
pending retry — so you can confirm at a glance that auto-review is on and working
without digging through logs.

> The older example automation at
> [`examples/auto_review.yaml`](examples/auto_review.yaml) still works but is
> **superseded** by this option — keep it only for custom needs.

## Example automations

Two ready-to-paste automations live in [`examples/`](examples/):

| File | What it does |
|---|---|
| [`auto_message.yaml`](examples/auto_message.yaml) | Sends a welcome message the moment a booking is confirmed |
| [`auto_review.yaml`](examples/auto_review.yaml) | Auto-posts a 5★ review (legacy — superseded by the built-in [Auto-Review](#auto-review) option) |

See [`examples/README.md`](examples/README.md) for details and personalisation tips.

## Events

### `localtrailerhire_booking_request_received`

Fired the first time a booking shows up with a `request-payment` transition
(or `request-payment-after-enquiry`) — i.e. an incoming request that needs the
host to accept or decline.

**Event data:** same fields as `localtrailerhire_booking_confirmed` below.

**Example:**
```yaml
automation:
  - alias: "Notify on booking request"
    trigger:
      - platform: event
        event_type: localtrailerhire_booking_request_received
    action:
      - service: notify.mobile_app
        data:
          title: "New booking request"
          message: >
            {{ trigger.event.data.customer_first_name }} wants to book
            {{ trigger.event.data.listing_title }} from
            {{ trigger.event.data.booking_start }}.
```

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

### `localtrailerhire_review_left`

Fired when a provider review is successfully posted via the `leave_review`
service.

**Event Data:**
- `transaction_id`: The transaction the review was posted on
- `transition`: Which review transition was used (`review-1` or `review-2`)
- `rating`: The star rating that was posted (1-5)
- `timestamp`: When the review was posted

## Sample Dashboard

A ready-to-use Lovelace dashboard is included at
[`dashboards/local_trailer_hire.yaml`](dashboards/local_trailer_hire.yaml). It
shows the calendar, top-line stats, earnings by period, a reputation &
messages section (rating, reviews, acceptance/response rate, awaiting-reply
banner), a pending-action banner with quick accept/decline buttons, and a
per-listing view.

To use it:
1. Settings → Dashboards → **Add Dashboard** → New dashboard from scratch
2. Open the new dashboard, three-dots → **Edit dashboard**
3. Three-dots → **Raw configuration editor**
4. Paste the contents of the YAML file and save

## Per-Listing Devices

Each of your trailers (`own_listings`) becomes its own Home Assistant device,
linked to the integration as a child device. Per-listing entities:

- `sensor.<title>_state` — `published`, `closed`, `draft`, or `pendingApproval`
  (attributes include `public_url`, a "view on site" link to the listing)
- `sensor.<title>_price` — daily price in AUD
- `sensor.<title>_active_bookings` — count of upcoming + in-progress bookings on that listing

New listings are picked up on next integration reload.

## Troubleshooting

### Authentication Issues

- Ensure your email and password are correct (the same ones you use on localtrailerhire.com.au)
- The marketplace client ID is built in — you don't need to provide one
- If auth keeps failing, remove and re-add the integration to re-authenticate
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

- **Auth**: `POST https://flex-api.sharetribe.com/v1/auth/token`
- **Transactions**: `GET .../v1/api/transactions/query`
- **Transition**: `POST .../v1/api/transactions/transition` (accept/decline/review)
- **Send message**: `POST .../v1/api/messages/send`
- **Read messages**: `GET .../v1/api/messages/query` *(v1.4.0)*
- **Own listings**: `GET .../v1/api/own_listings/query`
- **Reviews**: `GET .../v1/api/reviews/query?subjectId=<you>` *(v1.3.0)*
- **Current user**: `GET .../v1/api/current_user/show` *(profile + stats)*

The integration uses JSON format (`Accept: application/json`) for queries and Transit format (`application/transit+json`) for sending messages, matching the Sharetribe web application behavior.

📖 **Full, empirically-verified API reference:** [`docs/SHARETRIBE_API.md`](docs/SHARETRIBE_API.md) — every endpoint, auth flow, payload shape, and transition, probed live against the marketplace (not just copied from Sharetribe's docs, which were wrong in several places).

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
