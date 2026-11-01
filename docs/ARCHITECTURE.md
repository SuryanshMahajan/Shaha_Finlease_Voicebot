# Architecture

## Components

- **Next.js (`voicebot/`)** provides the admin dashboard, customer tools, call history, callback follow-up, transcripts, and reports. Browser API requests use the configured `NEXT_PUBLIC_API_URL`; the short-lived admin token stays in memory and is cleared on logout or expiry.
- **FastAPI (`service/app/`)** enforces administrator authentication on customer, call, callback, transcript, summary, and reporting routes. Pydantic schemas validate inbound data; SQLAlchemy models and Alembic migrations own PostgreSQL persistence.
- **PostgreSQL 16** remains the existing default/rollback database. The additive assignment overlay in `docker-compose.sqlserver.yml` uses SQL Server Developer with an independent `assignment_sqlserver_data` volume and SQLAlchemy's pymssql driver. Its Alembic baseline creates the current metadata schema. No existing PostgreSQL rows are copied or modified by the overlay.
- **Voice interfaces (`service/app/services/`)** define provider boundaries for speech recognition, language models, speech generation, telephony, conversation orchestration, and call analysis. The Hindi/English conversation engine is deterministic. The inbound Twilio Conversation Relay adapter validates Twilio signatures with the official SDK, verifies the initial setup frame, and routes final prompts to that engine. Prompts remain transient and are not written as transcripts. Provider calls have bounded timeout/retry helpers; local test doubles mark output as mock and simulated. No outbound dialer is implemented.

## Outbound workflow safeguards

Outbound workflows are disabled by default. Enabling the environment flag still does not connect telephony or place a call: the API only permits creation of an operational call record when a customer has documented consent timestamp and source, is not marked do-not-call, and the configured timezone is within the configured calling window. Customer CSV import never grants consent. Existing customers migrate to no recorded consent.

Call records are marked simulated by default. Signed inbound Twilio requests can create non-simulated operational records identified by Twilio Call SID; caller phone numbers are not stored. Transcript and summary content is hidden for simulated records. Internal provider services can persist transcript segments and summaries only for records explicitly created as non-simulated, with provenance; the Relay adapter does not currently persist transcript or summary content. Twilio credentials and a public origin are optional backend configuration and remain unconfigured unless explicitly supplied. Summary retry attempts are recorded as failed with a provider-unconfigured code rather than fabricated as successful.

Queued operational records can be closed as completed, failed, or disconnected, with an append-only event history; signed Relay sessions also transition through connected. The protected provider-readiness endpoint reports configured state and active session count, never secrets. A configured state is not proof of a connected session.

Twilio endpoints are provider-authenticated by `X-Twilio-Signature` against the configured canonical public URL; they do not use browser administrator tokens. A reachable public HTTPS/WSS endpoint and matching Twilio Voice application configuration are required. Voice identity verification remains disabled because no trusted customer mapping exists, and no financial disclosure is available from the voice flow.

## Identity and data protection

Name and birth-year verification is rate-limited and audited without retaining submitted answers. Verification history stores per-customer result and time; it does not authorize access to financial data. No financial-disclosure endpoint exists. Audit logs use allowlisted metadata and omit customer values, notes, passwords, tokens, and verification factors.

## Local assignment simulator

The authenticated `/api/demo/persona/{persona}` and `/api/demo/run-suite` routes use the deterministic state machine and scripted fictional responses. The suite saves twelve simulated attempts atomically: each of six outcomes twice, including third-party without callback. Scripted transcript and summary rows use `local_simulation`; callback schedules are created with their outcome, verification attempts create outcome-only `VerificationEvent` rows linked to the call. Summaries are exactly three lines.

The Call Console also opens an authenticated `/api/voice-sessions` simulation for fictional `DEMO-` customers. The browser requests microphone permission, uses Web Speech Recognition only when on-device processing is available, sends recognized text through the deterministic safety engine, and speaks replies with `speechSynthesis`. Audio is not sent to or stored by the application; recognized text and replies are retained with `browser_voice` provenance. Verification turns are replaced with a redaction marker. Turn UUIDs and stored results make request retries idempotent without retaining utterance text in the idempotency table. Browser timing samples run from utterance-end to speech-synthesis-start, not acoustic output. SQL Server migrations through `0010_voice_turn_idempotency` and the text-only API flow have been verified locally; browser/device audio behavior remains unverified.

An optional Gemini adapter is disabled by default (`LLM_PROVIDER=none`). If explicitly enabled, it receives only generic small-talk text after a local sensitive-content check; it receives no customer record or verification factors. A response filter rejects financial/account language. Provider configuration alone is not proof of a successful model call. Free-tier quota and data-use terms depend on Google's current offering.

Append-only `DoNotCallEvent` rows track requested restrictions and separately authorized releases. Normal customer edits cannot clear an active restriction; the release route requires a reason. Outbound remains disabled.

## Network and local configuration

Compose services share an internal network. The backend uses PostgreSQL service name `db` in Compose and `localhost` for host development. PostgreSQL is published only on loopback. CORS origins, admin credentials, JWT secret, provider boundaries, outbound enablement, timezone, and calling window are configured through environment variables. Keep `.env` local and use synthetic customer records.
