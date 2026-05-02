# Example automations

Drop-in Home Assistant automation YAMLs for the Local Trailer Hire
integration. Paste them into `automations.yaml` (or via Settings →
Automations & Scenes → Create automation → ⋮ → Edit in YAML).

| File | What it does | Triggers on |
|---|---|---|
| [`auto_message.yaml`](auto_message.yaml) | Sends a friendly welcome message to the customer when a booking is confirmed (pickup hint + your contact number). | `localtrailerhire_booking_confirmed` |
| [`auto_review.yaml`](auto_review.yaml) | Waits until `booking_end + 4 hours`, then posts a 5-star provider review automatically. | `localtrailerhire_booking_confirmed` |

Both rely on events fired by the integration's coordinator on every
refresh cycle. They're idempotent — the integration's storage layer
records when a message has been sent / event has fired so duplicates
won't go out across HA restarts or re-imports of the same transaction.

## Combining them

Both automations trigger on the same event so they'll run in parallel.
The message goes out immediately on confirmation; the review fires hours
after booking end. No interaction needed between them.

## Personalising

- **Auto-message:** edit the `message` template in `auto_message.yaml` to
  match your tone, drop your phone number, or strip the Apple Maps caveat.
- **Auto-review:** edit `review_content` in `auto_review.yaml` and the
  `(4 * 3600)` buffer to push the review later if you want more buffer
  for late returns. Sharetribe enforces a review window after delivery,
  so don't push it past ~5 days.
