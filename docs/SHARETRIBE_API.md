# Sharetribe Flex / LocalTrailerHire — API Reference (empirically verified)

> **Why this file exists:** a durable, account-independent record of the Sharetribe
> Flex Marketplace API as actually used by `localtrailerhire.com.au` — so the
> integration can be understood and rebuilt even if access to Sharetribe's docs,
> console, or the marketplace is lost. Read-only coverage was re-audited on
> **2026-08-22**: 135 transactions (2 pages), 432 messages across 118
> transactions, 45 provider reviews, and 1 own listing. These aggregate counts
> are recorded for completeness checks; no customer values are retained here.
>
> **Trust note:** every endpoint and shape below was **probed live** against the
> marketplace (read-only, 2026-06-22) — NOT taken on faith from Sharetribe's
> published docs, which were wrong in several places (see §0). Shapes are real;
> no credentials or customer PII are recorded here.

---

## 0. Where the published docs are WRONG (empirical corrections)

| Docs say | Reality (probed) |
|---|---|
| `reviews/query` filters by `by` / `for` / `subject` | **Only `subjectId` works.** `by`/`for`/`subject`/no-params all → `400 validation-invalid-params`. |
| `grant_type=anonymous` is supported | **`400 Bad request`** with `client_id` only. Public reads here use the **user token**. |
| `GET /v1/api/sitemap/listings` exists | **`404`** on this marketplace. |
| `bookings/query?transactionId=` | **`400 validation-missing-key`** — transactionId alone is not accepted; bookings are read via `transactions/query?include=booking` instead. |
| `availability_exceptions/query?listingId=` | **`400 validation-missing-key`** — needs `start`+`end` too. |
| `stock_adjustments/query?listingId=` | **`400 validation-missing-key`** — this marketplace is availability-based, not stock-based. |
| `process_transitions/query` | **`400`** without `processName`/`transactionProcessAlias`. |

Everything in §6 is annotated with its probed status.

---

## 1. Overview

- **Platform:** Sharetribe Flex. `localtrailerhire.com.au` is a Sharetribe Web
  Template front-end on this same backend.
- **Role:** the integration authenticates as a **provider (host)** — host-side
  reads + a few writes (send message, transition, leave review). It only sees the
  logged-in host's data (not an operator/Integration-API tool).
- **Marketplace (host) API base:** `https://flex-api.sharetribe.com`
  - Auth: `…/v1/auth/token` · Resources: `…/v1/api/<resource>/<action>`
- **Client ID (public, not secret):** `ed212165-eae2-4fcc-8739-e057ca16d2df`
  (`LOCALTRAILERHIRE_CLIENT_ID`) — the web-app client id, same for every browser.
- A separate **Integration API** (`flex-integ-api.sharetribe.com`) exists for
  operators with marketplace-wide access; **not used** here.

---

## 2. Authentication (`/v1/auth/token`)  [verified]

`POST …/v1/auth/token`, body `application/x-www-form-urlencoded`,
`Accept: application/json`.

| grant_type | Body | Probed |
|---|---|---|
| `password` | `client_id`,`username`,`password`,`scope=user` | ✅ works |
| `refresh_token` | `client_id`,`refresh_token` | ✅ (used in prod) |
| `anonymous` | `client_id` | ❌ `400 Bad request` |

Token response keys **[verified]**: `access_token`, `refresh_token`, `scope`,
`token_type` (`bearer`), `expires_in` (seconds).

Rules (`api.py`): send `Authorization: Bearer <access_token>` on every call;
refresh `TOKEN_REFRESH_BUFFER=60`s before expiry; **refresh tokens rotate** —
persist the newest one; on `401` refresh once and retry. Revoke:
`POST /v1/auth/token/revoke` with `token=<refresh_token>`.

---

## 3. JSON:API envelope / pagination / include  [verified]

```json
{
  "data": { "id": {"uuid":"..."}, "type": "transaction",
            "attributes": {...}, "relationships": {...} },
  "included": [ { "id": {"uuid":"..."}, "type": "booking", "attributes": {...} } ],
  "meta": { "totalItems": 135, "totalPages": 2, "page": 1, "perPage": 100 }
}
```
- IDs are `{"uuid":"..."}` objects (`_extract_uuid` also tolerates bare strings).
- Pagination: `page` + `per_page` (max 100). Loop until short page or `MAX_PAGES=50`.
- `include=a,b` embeds related resources into `included`.

---

## 4. Content-type split — JSON vs Transit  [verified]

- Reads & most writes: `Accept: application/json`.
- **`messages/send` only:** `application/transit+json`. Body is a Transit array:
  `["^ ", "~:transactionId", "~u<uuid>", "~:content", "<text>"]`
  (`~u`=UUID, `~:`=keyword). `transactions/transition` accepts plain JSON.

---

## 5. Endpoints the integration uses  [all verified ✅]

| Purpose | Method · Path | Content | `api.py` | const |
|---|---|---|---|---|
| Token | POST `/v1/auth/token` | form | `_do_password_grant`/`_do_refresh_token` | `AUTH_TOKEN_URL` |
| Query transactions | GET `/v1/api/transactions/query` | JSON | `get_transactions` | `TRANSACTIONS_URL` |
| Transition | POST `/v1/api/transactions/transition` | JSON | `transition_transaction`,`leave_review` | `TRANSITION_URL` |
| Send message | POST `/v1/api/messages/send` | **Transit** | `send_message` | `MESSAGE_SEND_URL` |
| Own listings | GET `/v1/api/own_listings/query` | JSON | `get_own_listings` | `OWN_LISTINGS_URL` |
| Reviews | GET `/v1/api/reviews/query` | JSON | `get_reviews` | `REVIEWS_URL` |
| Current user | GET `/v1/api/current_user/show` | JSON | `get_current_user_id` | `CURRENT_USER_URL` |

Verified request details:
- `transactions/query?only=sale&per_page=100&page=N&include=booking,customer,listing[,provider]`
  (optional `lastTransitions=<csv>`). This account: **135** transactions over
  **2 pages** at the 2026-08-22 audit.
- `own_listings/query?per_page=100&page=N&include=images`. This account: **1** listing.
- `reviews/query?subjectId=<currentUserId>&per_page=100&page=N` → reviews about the
  provider (`type=ofProvider`, `state=public`). **`subjectId` is the only working
  filter.** This account: **45** reviews at the 2026-08-22 audit.
- `messages/query?transactionId=<id>&include=sender&per_page=100&page=N` → message
  history with sender relationships. The completeness audit found **432**
  messages across **118** transactions.
- `transactions/transition` body `{"id","transition","params"}`; review params
  `{"reviewRating":1-5,"reviewContent":"..."}`.

---

## 6. Full endpoint catalogue (probed where reachable)

`✅`=verified 200, `❌`=docs wrong/unavailable, `⚠️`=exists but needs more params,
`—`=not probed (mutating POST — would change live data), `A`=anon-or-user, `U`=user.

**Auth** ✅ POST `/v1/auth/token` (password,refresh_token; `anonymous`❌) · — POST `/v1/auth/token/revoke`

**Marketplace** ✅ GET `/v1/api/marketplace/show` → attrs `{name, description}`

**Users** ✅ GET `/v1/api/users/show?id=` (U) → public profile `{banned,deleted,createdAt,state,profile}` (no email)

**Current user** ✅ GET `/v1/api/current_user/show` (U) · — POST `…/create`,`…/create_with_idp`,`…/update_profile`,`…/change_password`,`…/change_email`,`…/verify_email`,`…/send_verification_email`,`…/delete`

**Password reset** — POST `/v1/api/password_reset/request`,`…/reset`

**Listings (public)** ✅ GET `/v1/api/listings/query` (U; needs user token here, anon❌) → **1307** public listings · ✅ GET `/v1/api/listings/show?id=`

**Own listings** ✅ GET `/v1/api/own_listings/query` · ✅ GET `…/own_listings/show?id=` · — POST `…/create`,`…/create_draft`,`…/update`,`…/publish_draft`,`…/discard_draft`,`…/close`,`…/open`,`…/add_image`

**Images** — POST `/v1/api/images/upload` (U, multipart `image`)

**Availability exceptions** ⚠️ GET `/v1/api/availability_exceptions/query` (needs `listingId`+`start`+`end`; listingId-only → 400) · — POST `…/create`,`…/delete`

**Time slots** ✅ GET `/v1/api/timeslots/query?listingId&start&end` → `{type,seats,start,end}`

**Stock** ⚠️/— `…/stock/compare_and_set`, `…/stock_adjustments/query` (400 missing-key — not used by this availability-based marketplace)

**Bookings** ⚠️ GET `/v1/api/bookings/query` (`transactionId` alone → 400; use `transactions/query?include=booking`)

**Transactions** ✅ GET `…/transactions/show?id=` · ✅ GET `…/transactions/query` (U) · — POST `…/initiate`,`…/speculatively_initiate`,`…/transition`,`…/speculatively_transition`

**Process transitions** ⚠️ GET `/v1/api/process_transitions/query` (needs `processName`/`transactionProcessAlias`)

**Reviews** ✅ GET `/v1/api/reviews/query?subjectId=` · ✅ GET `…/reviews/show?id=`

**Messages** ✅ GET `/v1/api/messages/query?transactionId=[&include=sender]` · — POST `/v1/api/messages/send` (Transit)

**Stripe** ✅ GET `/v1/api/stripe_account/fetch` → `{stripeAccountId, stripeAccountData}` · — POST `…/stripe_account/create`·`/update`, `…/stripe_account_links/create`, `…/stripe_persons/create`, `…/stripe_setup_intents/create`, `…/stripe_customer/*`

**Files** — `…/files/*`, `…/own_files/*`, `…/file_uploads/create`, `…/file_downloads/create`

**Sitemap** ❌ GET `/v1/api/sitemap/listings` → **404** (unavailable)

---

## 7. Entity shapes — real fields [verified]

PII *values* omitted; field *names* are the schema. `money = {amount:<int cents>, currency:"AUD"}` → ÷100.

### current_user (`type=currentUser`)
`attributes`: `email`, `deleted`, `banned`, `state` (`active`), `createdAt`,
`emailVerified`, `pendingEmail`, `identityProviders[]`,
`stripeConnected`/`stripePayoutsEnabled`/`stripeChargesEnabled` (bools),
`permissions.{read,initiateTransactions,postListings}`, `profile`.
`profile`: `displayName`, `firstName`, `lastName`, `bio`, `publicData`,
`protectedData`, `privateData`, `metadata`.
**`profile.privateData` goldmine** — `bookingStats-<YYYY>` and `bookingStats-<YYYY-MM>`
objects, each with: `acceptanceRate`, `responseRate`, `numBookings`, `numHires`,
`numTransactions`, `numBookingRequests`, `numAcceptedBookings`,
`numDeclinedBookings`, `numExpiredBookings`, `numCancelledBookings`,
`numAbortedBookings`, `missedEarnings`, `missedEarningsDueToDeclinedBookings`,
`missedEarningsDueToExpiredBookings`, `missedEarningsDueToAbortedBookings`,
`updatedAt`. (Great source for future "host performance" sensors.)
→ `data.id.uuid` is the provider id used as reviews `subjectId`.

### transaction (`type=transaction`)
`attributes`: `processName` (e.g. `customer-cancel`, `default-booking` — **multiple
processes exist**), `processVersion` (int), `state` (e.g. `state/accepted` — note
the `state/` prefix), `transitions[]` (`{transition, createdAt, by}` history),
`lastTransition`, `lastTransitionedAt`, `createdAt`, `payinTotal`/`payoutTotal`
(money), `lineItems[]`, `protectedData`, `metadata`.
`relationships`: `booking`, `listing`, `customer`, `provider` (+ `reviews`, `messages`).
- **lineItems[]**: `{code (e.g. "line-item/units"), unitPrice (money), lineTotal
  (money), quantity (int), reversal (bool), includeFor[] ("customer"/"provider")}`.
- **protectedData** (customer-entered; PII field names): `firstName`, `lastName`,
  `phoneNumber`, `providerPhoneNumber`, `residentialAddress`,
  `driversLicenceNumber`, `driversLicenceIssuedBy`,
  `driversLicenceExpiryDate{day,month,year}`, `liabilityExcess`, `bookingType`,
  `promoCode`, `termsAccept[]`, `howDidYouHearAboutUs`, `signupMethod`.
  (Field naming varies by process — also seen `customerPhoneNumber`,
  `pickupAddress`/`address`, `suburb`, `building`; the parser checks several.)

### booking (included `type=booking`)
`{start, end, displayStart, displayEnd, state (e.g. "accepted"), seats}`. Integration
categorises by `start`/`end` vs UTC now (§8).

### user / customer (included `type=user`)
`profile`: `displayName`, `abbreviatedName`, `bio`, `metadata`,
`publicData.{numCustomerHires, customerReviewStats{avgCustomerReviewRating,
numCustomerReviews, updatedAt}}`. (Customer contact details live in the
transaction `protectedData`, not here.)

Important parser rule: this marketplace's included customer profiles do not
provide `firstName` / `lastName`; those names must fall back to transaction
`protectedData.firstName` / `protectedData.lastName`. The 2026-08-22 audit found
usable protected customer details on 120 transactions and zero profile-level
first/last names.

### listing / ownListing
Common `attributes`: `title`, `description`, `state`
(`published`/`closed`/`draft`/`pendingApproval`), `deleted`, `price` (money),
`geolocation{lat,lng}`, `availabilityPlan{type:"availability-plan/time", timezone
[, entries[]{dayOfWeek,seats,startTime,endTime}]}`, `createdAt`, `metadata`,
`publicData`. **`ownListing`** also exposes `privateData` (`discountCodes[]{code,
percentDiscount,singleUse[],usedOn}`, `marketValue`, `subscription{...}`) and
`metadata.subscription{type e.g. "premium-monthly", billing{...}}`.
**`publicData`** (trailer details): `amenities[]`, `category`, `size`, `tare`,
`registration`, `yearOfManufacture`, `dimensions{lengthMetres,widthMetres}`,
`instantBook`, `leadTime`, `minDuration`, `hasDiscountCodes`,
`liabilityConfig{baseValue,tier}`, `location{address,building}`,
`openingHours.entries[]{dayOfWeek,startTime,endTime}`, `priceDiscount1..4`.
`relationships.images.data[]` → included `type=image`,
`attributes.variants.<name>.{url,width,height,name}` (the integration requests
`landscape-crop2x`/`landscape-crop`, falls back to `default`).

### review (`type=review`) — `reviews/query?subjectId=<uid>`
`{type ("ofProvider"|"ofCustomer"), state ("public"|"pending"), deleted, rating
(1-5 int), content, createdAt}`. Relationships (`author`,`subject`,`listing`)
appear only with `include=`.

### message (`type=message`) — `messages/query?transactionId=<id>`
`{content, createdAt, deleted}`. Use `include=sender` to get the `sender`
relationship (needed to tell customer messages from your own).

---

## 8. Transitions & review lifecycle  [verified]

Booking categorisation (vs UTC now): `upcoming` start≥now · `in_progress`
start≤now<end · `past` end<now · `unknown` missing date.

**Multiple transaction processes exist** (`customer-cancel`, `default-booking`,
…); transitions are process-specific. Observed `lastTransition` values (probed):
`confirm-payment-instant-book`, `request-payment*`, `accept`, `complete`,
`review-1-by-customer`, `review-1-by-provider`, `review-2-by-customer`,
`review-2-by-provider`, `expire-review-period`, `expire-customer-review-period`,
`expire-provider-review-period`, `enquire`, `expire-payment`, `cancel-by-customer`,
`payout-after-cancel-without-refund`. All prefixed `transition/`.

`const.py` frozensets: `CONFIRMED_TRANSITIONS` (→ booking_confirmed event;
includes both `confirm-payment-instant-book` and `…-instant-booking`),
`REQUEST_TRANSITIONS` (request-payment*), `PAYOUT_TRANSITIONS` (earned),
`PROVIDER_REVIEW_TRANSITIONS` (review-1/2-by-provider), and
`PROVIDER_REVIEW_DONE_TRANSITIONS` (provider review transitions plus
`review-2-by-customer`, review-period/customer/provider expiry, and
`payout-after-reviews` → already reviewed or terminal; auto-review skips).

Auto-review eligibility also checks the full `transitions[]` history. This is
required when the provider reviewed first and a later customer/payout transition
has replaced the provider review as `lastTransition`. Failed attempts use a
persisted exponential backoff rather than a small fixed attempt budget.

**Provider review** = `transactions/transition` with `review-1-by-provider`
(or `-2-`) + `params{reviewRating,reviewContent}`. Miss the window →
`expire-provider-review-period` and the review is lost (what auto-review prevents).

---

## 9. Rate limits & errors  [verified shapes]

- Retries: HTTP **429** and transient **502/503/504** with backoff honouring
  `Retry-After` (`RETRYABLE_STATUSES`, `MAX_RATE_LIMIT_RETRIES=3`,
  `MAX_RETRY_AFTER_SECONDS=300`).
- Error envelope: `{"errors":[{"id","status","code","title","details"}]}`. Codes
  seen: `validation-invalid-params`, `validation-missing-key`. The integration
  raises `AuthenticationError` (401) / `APIError` (other), never logs tokens/PII.

### Local retention model

The integration keeps a customer-id keyed archive in its per-config-entry Home
Assistant storage. Each customer record retains a bounded transaction summary,
so details remain available if a later API response omits an older transaction.
Names, public hire/review stats and booking references are retained by default.
Phone, address, licence and referrer values are retained only when **Include
sensitive customer details** is enabled; disabling that option scrubs previously
stored sensitive values on the next successful refresh. Diagnostics report only
the archive count and redact customer names/contact fields.

Message-body retention is a separate, explicit opt-in. Normal polling reads only
a bounded set of active bookings (`MAX_MESSAGE_SCAN=25`); the archive additionally
syncs a small rotating batch and stops when it reaches a stable message ID already
stored. Because Sharetribe exposes no message timestamp filter, the manual
`sync_message_history` service advances a persisted, rate-limited cursor in
batches instead of issuing 100+ requests every ten minutes. Both archives support
90-day, one-year, or forever retention and JSON/CSV service-response exports.

---

## 10. Reproducible examples (creds via env, not inline)

```bash
CID=ed212165-eae2-4fcc-8739-e057ca16d2df ; BASE=https://flex-api.sharetribe.com
TOKEN=$(curl -s -X POST "$BASE/v1/auth/token" -d grant_type=password -d client_id=$CID \
  --data-urlencode username="$LTH_USER" --data-urlencode password="$LTH_PASS" -d scope=user | jq -r .access_token)
curl -s "$BASE/v1/api/current_user/show" -H "Authorization: Bearer $TOKEN"          # → data.id.uuid
UID=<uuid>; curl -s "$BASE/v1/api/reviews/query?subjectId=$UID&per_page=100" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/v1/api/transactions/query?only=sale&per_page=100&include=booking,customer,listing" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/v1/api/messages/query?transactionId=<txn>&include=sender" -H "Authorization: Bearer $TOKEN"
# Provider review (mutating):
curl -s -X POST "$BASE/v1/api/transactions/transition" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"id":"<txn>","transition":"transition/review-1-by-provider","params":{"reviewRating":5,"reviewContent":"..."}}'
# Send message (Transit, mutating):
curl -s -X POST "$BASE/v1/api/messages/send" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/transit+json" -H "Accept: application/transit+json" \
  -d '["^ ","~:transactionId","~u<txn>","~:content","Hello"]'
```

## 11. References (cross-check only — the live API above wins on conflict)

- Marketplace API: https://www.sharetribe.com/api-reference/marketplace.html
- Authentication API: https://www.sharetribe.com/api-reference/authentication.html
- Transaction processes: https://www.sharetribe.com/docs/concepts/transaction-process/
- Integration source of truth: `custom_components/localtrailerhire/{api,const}.py`
