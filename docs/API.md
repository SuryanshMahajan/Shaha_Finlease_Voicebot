# API

Base path: `/api`. JSON errors use FastAPI's `{ "detail": ... }` structure. Pagination accepts `limit` (1–100, default 50) and `offset` (0+, default 0). Invalid inputs return 422; missing records return 404.

## Health

- `GET /api/health` returns `{"status":"ok","environment":"development"}`.
- `GET /api/health/ready` runs `SELECT 1`; returns `{"status":"ready","database":"connected"}` or 503 `{"detail":"Database unavailable"}`.

## Customers

- `GET /api/customers?limit=20&offset=0&search=...` returns a bounded page. Search matches customer reference, display name, or phone suffix. Items contain only ID, customer reference, display name, phone last four digits, verification state, and creation time; birth year and full phone numbers are never returned.
- `GET /api/customers/{customer_id}` returns one minimized customer record or 404.
- `POST /api/customers` creates a customer from `customer_ref`, `display_name`, and `birth_year`; the response never includes the birth year. Duplicate references return 409.
- `PATCH /api/customers/{customer_id}` updates those identity fields and resets verification to unverified.
- Customer create/update can also record `outbound_consent_at` with timezone and `consent_source`, or set `do_not_call`. Consent time and source must be provided together. CSV imports do not grant consent.
- `GET /api/customers/{customer_id}/verification-history` returns the protected customer's verification outcomes and timestamps without submitted answers.
- `GET /api/customers/{customer_id}/demo-verification-fixture` is rate-limited and administrator-only. It returns name and birth year only for fictional `DEMO-` seed records; use it only for evaluator demonstrations. Ordinary customer responses never contain verification answers.
- `POST /api/customers/import/preview` validates the CSV and returns duplicate/rejected counts and a limited preview with reference, display name, and phone suffix. Birth years are not returned.
- `POST /api/customers/import` accepts `multipart/form-data` with a `file` field containing a UTF-8 CSV. Required headers: `customer_ref`, `display_name`, `birth_year`; optional header: `phone`. Files are limited to 2 MiB and 10,000 data rows. Phone numbers are validated and reduced to their last four digits. Customer references are normalized and are the duplicate identifier; phone numbers alone are not treated as unique. Response includes total, imported, duplicate, and rejected row counts plus row/field validation errors without echoing row values.
- `POST /api/customers/{customer_id}/verify` accepts `{"display_name":"Asha Devi","birth_year":"1980"}`. Both factors must match after whitespace/Unicode/case normalization. Success marks the record verified. Wrong factors, missing factors, and nonexistent IDs return the same generic failure body. This endpoint does not authorize access to financial information; no financial disclosure endpoint exists.

Example CSV:

```csv
customer_ref,display_name,birth_year,phone
DEV-0001,Asha Devi,1980,+91 98765 43210
```

## Calls

- `GET /api/calls?limit=50&offset=0` returns a paginated list without transcripts.
- `POST /api/calls` creates an operational record. Example: `{"direction":"inbound","callback_requested":false}`. Optional `customer_id` must exist. Returns 201 and the call record. This endpoint records a call; it does not place one.
- `GET /api/calls/{call_id}` returns one record or 404.
- `PATCH /api/calls/{call_id}/outcome` accepts one of `right_customer`, `wrong_number`, `third_party_answered`, `callback_requested`, `verification_failed`, or `not_connected`.
- `PATCH /api/calls/{call_id}/status` moves a queued operational record to `completed`, `failed`, or `disconnected`. Terminal records cannot transition again. This records an admin-reviewed lifecycle state; it does not prove a call connected or took place.
- `GET /api/calls/{call_id}/events` returns the minimal lifecycle event name, status, and timestamp. Call event history contains no submitted identity factors or transcript text.
- Call list/detail records include linked customer reference/name, verification status, duration when an end timestamp exists, simulation status, and transcript availability.
- Call records are marked `simulated` by default. `GET /api/calls/{call_id}/transcript` returns transcript segments only when provenance matches the record's simulation channel or provider source, including speaker, timestamp, language, and provenance.
- `GET /api/calls/{call_id}/summary` returns processing status and a summary only when one has been persisted from transcript content. `POST /api/calls/{call_id}/summary/retry` refuses simulated calls and calls without transcripts. Since no LLM provider is configured, a valid retry is recorded as failed with `provider_unconfigured`; no summary is invented.
- `POST /api/voice-sessions` starts a browser simulation for a fictional demo customer and selected `en`/`hi` language. `POST /api/voice-sessions/{call_id}/turn` receives recognized or explicitly typed text and an optional client-generated `turn_id` UUID. Replaying the same turn ID returns the persisted response without storing a second turn. `POST /api/voice-sessions/{call_id}/metrics` accepts ordered browser lifecycle timestamps; `POST /api/voice-sessions/{call_id}/end` closes the session. All require administrator auth. Verification turns are redacted from saved transcripts; browser voice remains simulated.
- `GET /api/customers/{customer_id}/do-not-call-events` returns opt-out history. `POST /api/customers/{customer_id}/do-not-call/release` requires a reason with at least 20 non-whitespace characters and adds an authorized release event. Standard customer edits cannot clear DNC.
- Setting a call outcome to `callback_requested` creates one pending or scheduled follow-up record. `GET /api/calls/{call_id}/callbacks` returns follow-up status history. `POST /api/calls/{call_id}/callbacks` schedules or creates a follow-up; `PATCH /api/callbacks/{callback_id}` moves an open follow-up to `scheduled`, `completed`, `cancelled`, or `missed`. A partial unique index prevents more than one pending/scheduled follow-up per call.

## Provider readiness

- `GET /api/providers/status` is administrator-only and returns configured/mode flags for STT, optional Gemini, LLM, TTS, telephony, and analysis, plus outbound enablement and Twilio Relay readiness. Twilio reports `unconfigured`, `configured`, or `connected` with an active-session count; no credentials are returned. Built-in adapters remain simulated.

## Twilio Conversation Relay

- `POST /api/twilio/voice` is a Twilio inbound Voice webhook. It validates `X-Twilio-Signature` with Twilio's official Python SDK using the configured public HTTPS origin, checks the Account SID, and creates an inbound call record without storing caller phone numbers. It returns TwiML that connects to the configured WSS Relay URL.
- `wss://<configured-origin>/api/twilio/relay` validates the initial WebSocket handshake signature and the first `setup` frame. It accepts inbound sessions only, routes final `prompt` messages through the deterministic Hindi/English conversation engine, handles interruption and language messages, and returns bounded `text`, `language`, or `end` messages. Unexpected disconnects and provider/protocol failures update lifecycle status; Relay utterances are not logged or persisted as transcripts.
- `POST /api/twilio/complete` validates the signed Twilio action webhook, records only allowlisted outcome/lifecycle values, and responds with fixed localized TwiML. It does not echo caller-provided handoff text.
- The three endpoints require `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PUBLIC_BASE_URL`. The base URL must be the externally visible HTTPS origin used by Twilio for signature validation. Missing configuration fails closed. These provider webhooks use Twilio signatures rather than the administrator bearer token.
- Relay identity verification and financial disclosure are unavailable: the voice connection has no trusted mapping to a customer record. A caller saying a name or birth year never authorizes access. No outbound dialer is implemented; this integration handles inbound calls only.

## Analytics

- `GET /api/analytics/overview` returns `{ "total_calls": 0, "verified_customers": 0, "callback_requests": 0, "failed_calls": 0 }` based on persisted data.
- `GET /api/analytics/dashboard` returns customer/call totals, successful customer contacts, DNC customer count, verification and pending/scheduled/completed callback counts, failed connections, six outcome counts, and counts by active call date (up to 14 days). It is administrator-only and all values come from saved records.
- `GET /api/customers` accepts `status=verified|unverified` in addition to pagination and permitted search fields.
- `GET /api/calls` accepts `outcome`, exact `customer_ref`, `date_from`, and `date_to` filters in addition to pagination.
- `GET /api/reports/calls` returns date-filtered outcome totals, daily activity, verification success/failure events, and pending/scheduled/completed/missed callback counts.
- Dashboard and report output include voice timing sample counts and averages only when samples have been persisted. No timing values are seeded.
- `GET /api/reports/calls.csv` exports up to 10,000 authorized call records with call ID, customer reference, direction, status, outcome, timestamps, duration, and callback flag. It excludes customer names, birth years, phone numbers, transcripts, and financial details.

All customer, call, callback, transcript, summary, analytics, and reporting routes require the configured administrator bearer token. Twilio webhooks are validated separately with Twilio request signatures. No financial-disclosure endpoint exists. Browser and scripted simulation transcripts are persisted with separate provenance; Relay prompts are not persisted as transcripts. Outbound workflows remain disabled and the Twilio adapter does not place calls. Do not use real customer data or expose this prototype publicly.

