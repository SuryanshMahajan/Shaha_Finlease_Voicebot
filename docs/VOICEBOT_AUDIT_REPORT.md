# Shaha Finlease Voicebot Audit

**Audit date:** 2026-11-01  
**Scope:** Read-only audit of the existing workspace, running local containers, and the SQL Server demo records. No application source, configuration, or database records were changed by this audit. This document is the only file added for the audit.

## A. Executive summary

**Verdict: READY FOR SIMULATED DEMO ONLY.** The application can demonstrate a deterministic, text-only persona flow, saved call rows, transcripts and three-line summaries, call history, and database-backed reporting code. The running frontend responds at `http://localhost:3000`; the backend readiness endpoint responds `{"status":"ready","database":"connected"}`. The active SQLAlchemy dialect is `mssql`.

There is **no browser voicebot loop**. The Call Console explicitly says it uses text personas and has no browser speech recognition or audio synthesis. No browser microphone, speech recognition, LLM, browser speech synthesis, or configured TTS/STT provider is present. An inbound Twilio Conversation Relay adapter exists in backend code, but the running app reports it unconfigured; its public endpoint and actual provider behavior have not been tested.

This is suitable for demonstrating the simulator and operator screens, after signing in with the locally configured administrator account. It is not ready for a live voice demo. The authenticated UI was not exercised end-to-end in a browser, so button-to-database behavior is not claimed as browser-verified.

The original assignment PDF was not found in project files. `docs/ASSIGNMENT_CHECKLIST.md` was used as the available requirements baseline. `README.md`, `docs/SETUP.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/BOT_PROMPT.md`, both Compose files, `.env.example` (read without reading `.env`), dependency manifests, models, migrations, routes, UI, and tests were inspected.

## B. Requirement matrix

Status labels use the requested categories. “Verified” means the specified non-destructive check actually ran; it does not mean a complete real-world voice workflow was tested.

| Requirement | Status | Evidence | How verified | Remaining gap |
|---|---|---|---|---|
| Browser requests microphone permission / captures audio | **NOT IMPLEMENTED** | `voicebot/src/app/call-console.tsx` exposes customer/persona selectors and buttons only; no `getUserMedia`, `MediaRecorder`, or audio capture path. | Source inspection and search for browser media APIs. | Add a permission-aware microphone capture flow. |
| Browser speech-to-text | **NOT IMPLEMENTED** | No `SpeechRecognition` / `webkitSpeechRecognition` use. `service/app/services/voice.py`: `MockSpeechToText.transcribe` returns a fixed placeholder. | Source inspection; `test_voice_providers.py` tests mock adapters. | Configure and exercise real STT or a browser-recognition implementation. |
| Send recognized browser speech to conversational backend | **NOT IMPLEMENTED** | Console calls only `api.demoPersona` and `api.demoSuite` in `voicebot/src/app/call-console.tsx`; no free-form turn endpoint or speech payload. | Source and API route inspection. | Add a live turn endpoint and connect real recognized input. |
| Contextual response generation / LLM | **SIMULATED / MOCK ONLY** | `service/app/services/conversation.py`: `detect_intent` and `ConversationEngine.handle` use fixed keyword rules and fixed responses. `MockLanguageModel.complete` returns a placeholder; no LLM client/configuration. | Source inspection and `test_conversation.py`, `test_voice_providers.py`. | No model call or natural language generation. |
| Browser speech synthesis / audible response playback | **NOT IMPLEMENTED** | No `speechSynthesis`, audio element, or audio playback in `voicebot/src`. `MockTextToSpeech.synthesize` returns `b"MOCK-AUDIO-NOT-SPEECH"`. | Source inspection and provider tests. | Add and test real TTS and browser playback. |
| Multiple user turns, silence, interruption, unclear speech, errors, cancel | **PARTIALLY IMPLEMENTED** | `ConversationEngine` is stateful for text; `TwilioRelaySession.handle` handles provider prompt, interrupt, language and error frames. Console has no turn input, microphone, playback, cancellation, or live timeout. Demo silence is a scripted 15-second result in `run_persona`. | `test_conversation.py` / `test_twilio_relay.py` simulate state and protocol messages; no browser test. | Real interaction lifecycle and browser error/cancel handling are absent. Relay behavior is not live-verified. |
| Meaningful English/Hindi handling | **SIMULATED / MOCK ONLY** | Fixed bilingual responses and keyword matching in `conversation.py`; `TwilioRelaySession` can switch on provider language metadata. Persona scripts choose Hindi for one persona. | Deterministic tests in `test_conversation.py` and protocol tests in `test_twilio_relay.py`. | No spoken Hindi/English recognition or audible language-quality test. |
| Verification, correct and incorrect factors | **SIMULATED / MOCK ONLY** | `ConversationEngine.submit_verification` accepts an injected verifier. The local `right_customer_hindi` and `wrong_birth_year_english` scripts in `demo.py` inject the known demo customer name and year from code; the Console does not collect/respond to those factors. `POST /api/customers/{id}/verify` is a separate authenticated CRUD verification endpoint. | `test_demo.py`, `test_conversation.py`, `test_customer_workflows.py`; DB contains two `right_customer` and two `verification_failed` calls but zero `verification_events`. | No actual voice verification; demo factors are supplied internally and simulated verification is not written to `VerificationEvent`. |
| Wrong number / third party / callback / no response / DNC personas | **SIMULATED / MOCK ONLY** | `run_persona` in `service/app/services/demo.py`; Console persona selector in `call-console.tsx`. `third_party_callback` scripts a fixed callback response; silence is fixed, not timed. | `test_demo.py`; persisted SQL Server outcomes include wrong number and callback. | No arbitrary respondent input. Third-party-without-callback is not one of the Console personas. DNC persona is not part of the five-persona suite. |
| Protect private data before verification / third party | **IMPLEMENTED BUT NOT VERIFIED** | `ConversationEngine` never includes customer data in replies; third party responses ask only about callback timing. Twilio Relay has no trusted customer mapping and converts verification request to identity-unavailable/handoff. No financial disclosure API exists. | `test_conversation.py::test_wrong_number_and_third_party_end_without_customer_disclosure`, `test_twilio_relay.py`, API/schema inspection. | No live provider/browser adversarial test. “Right customer” does not unlock financial details in this prototype. |
| Six outcome values stored and reported | **PARTIALLY IMPLEMENTED** | `CallOutcome` in `service/app/models/entities.py`; PATCH `/api/calls/{call_id}/outcome`; report and history code expose all six. Call History has an operator outcome selector for all six. Demo suite only produced five: right customer, wrong number, callback requested, verification failed, not connected. | Read-only SQL Server grouping: each of those five appears twice; `third_party_answered` appears zero times. Unit tests exercise enum and state handling. | UI can manually label an existing row with any outcome, but that is operator tagging, not proof that every conversational path works. Third-party no-callback path was not exercised against DB. |
| SQL Server active, migrations and persistence | **IMPLEMENTED AND VERIFIED** | `docker-compose.sqlserver.yml`, `service/app/scripts/prepare_sqlserver.py`, Alembic revisions through `0008_provider_sid_index`; backend readiness route. | Running health endpoint ready; runtime dialect `mssql`; Alembic version `0008_provider_sid_index`; `sqlserver` healthy. | SQL Server-specific behavior is not covered by the automated test suite; integration evidence is manual/local. |
| Customer / call / transcript / summary / callback / outcome persistence | **PARTIALLY IMPLEMENTED** | SQL Server tables/models in `service/app/models/entities.py`; `_save_demo_call`; persistence helpers in `call_records.py`. | Read-only DB snapshot below. | Callback schedule and verification event discrepancies described in section D. |
| Dashboard/report metrics and CSV | **IMPLEMENTED AND VERIFIED** | `dashboard_analytics`, `call_report`, `export_call_report` in `service/app/main.py`; `call_rates` in `metrics.py`; frontend `page.tsx` and `call-report.tsx`. Endpoints are admin-protected. | Called the three read-only handler functions against the live SQL Server session; dashboard and report aggregates were returned and CSV had 10 rows with the expected header. | The HTTP/authenticated browser route was not exercised. Report supports date filters; call-history filters include outcome, customer reference, dates, verification status, but not language/simulation status. Verification and callback discrepancies are in section D. |
| Actual utterance-end to first audible response latency and <3 sec target | **NOT IMPLEMENTED** | No browser audio pipeline, timestamp pair, latency field/API, or UI display. Demo durations are predetermined constants in `run_persona`. | Source search and provider inspection. | There are no actual latency samples; the target is not verified. |
| Outbound safety / calling window | **PARTIALLY IMPLEMENTED** | `create_call` in `main.py` rejects outbound workflow when disabled, requires consent and non-DNC when enabled, and calls `calling_window_open`; Compose hardcodes outbound disabled. No dialer is connected. | Unit tests in `test_outbound_safety.py`; runtime flag read as false. No call was placed. | Window policy truncates to minute, so `19:00:01` through `19:00:59` are still treated as minute 19:00. Tests cover minute boundaries, not seconds. No real outbound workflow exists. |
| DNC persistence and recontact prevention | **PARTIALLY IMPLEMENTED** | Demo opt-out sets `Customer.do_not_call` and adds a lifecycle event; demo/outbound routes reject a flagged customer; CSV import tests preserve existing DNC. | `test_demo.py`, `test_outbound_safety.py`, source inspection. | `update_customer` for `PATCH /api/customers/{customer_id}` and Customer Management edit UI allow an administrator to set `do_not_call` false; there is no immutable opt-out event/history or protection against an admin clearing the flag. DNC route was not run against the DB in this audit. |
| Automated-assistant and recording disclosure | **IMPLEMENTED BUT NOT VERIFIED** | Simulation opening in `ConversationEngine.start` says it is simulated and that a text transcript is saved; `welcome_live` identifies the automated assistant and says app audio is not stored. No audio recording field/storage path exists. | `test_simulation_greeting_is_clear_and_disallows_real_call_claim`; Twilio greeting protocol tests. | No live call was made; external provider audio processing/retention and live disclosure were not independently verified. |
| No financial details or credential requests | **IMPLEMENTED BUT NOT VERIFIED** | The state machine uses fixed responses, sensitive-topic handoff, no financial-data endpoint exists, and the voice adapter has no verified customer binding. It has no prompt asking for OTP, PIN, CVV, card details, or passwords. | `test_untrusted_instructions_cannot_change_policy_or_leak_prompt`; source/API inspection. | No real model/provider or live adversarial voice test. |
| Prompt manipulation cannot override verification policy | **IMPLEMENTED BUT NOT VERIFIED** | There is no LLM in the active path. `detect_intent` routes known instruction-override patterns to uncertainty; state-machine replies do not incorporate arbitrary prompts into protected data. | `test_untrusted_instructions_cannot_change_policy_or_leak_prompt`; no live LLM test is possible because none is connected. | Deterministic keyword handling is limited and not a general-purpose prompt-injection defense for a future model. |
| Authentication, data minimization, safe logs | **IMPLEMENTED BUT NOT VERIFIED** | `login`, `require_admin`, `audit_event` in `service/app/core/security.py`; admin dependency on customer/call/report routes; CSV allowlist; verification factors omitted from events/transcripts. Runtime checks confirmed admin username/hash are configured and JWT secret length is valid without displaying values. | `test_security.py`, `test_api.py`, workflow tests; readiness check. | No manual security penetration test. HTTP access-log behavior and deployment-level logging were not inspected. |
| Twilio inbound Relay / disclosure / no unexpected call | **BLOCKED BY MISSING CONFIGURATION** | `service/app/routers/twilio.py` and `service/app/services/twilio_relay.py` implement signed inbound webhook/WebSocket protocol. Runtime reports `twilio_conversation_relay` unconfigured, 0 sessions. Outbound disabled; Twilio code has no outbound dial path. | `test_twilio_relay.py` runs simulated sockets with injected signature validators; runtime readiness booleans checked. No real provider connection/call. | Requires account credentials and public HTTPS/WSS configuration; not appropriate to configure or call during this audit. External provider-side retention/recording behavior not verified. |
| Browser voice end-to-end and live Hindi/English tests | **NOT IMPLEMENTED** | No browser interaction test dependency or test files; only `npm` lint/typecheck/build. | No microphone permission, voice, or browser end-to-end test was run. | Build/lint do not establish microphone, STT, TTS, or actual user flow. |

## C. Voice pipeline

| Link | Status | Evidence |
|---|---|---|
| Microphone capture | **NOT IMPLEMENTED** | No browser media API in the Call Console. |
| Speech recognition | **NOT IMPLEMENTED in browser; mock standalone adapter** | `MockSpeechToText` is a placeholder. Twilio Conversation Relay could supply text from inbound audio when configured, but the local Relay is unconfigured. |
| Conversation engine / LLM | **Deterministic text engine only; no LLM** | `ConversationEngine` uses keyword matching and fixed response strings. Twilio Relay can pass final prompt text to it. `MockLanguageModel` is not invoked by the Console or Relay. |
| Response generation | **Scripted or rule-based** | Console personas call `/api/demo/persona/{persona}` and server-side `run_persona`; Relay gets fixed engine responses. |
| Speech synthesis | **No application/browser TTS; Twilio managed TTS only in a configured Relay deployment** | Mock adapter returns non-speech bytes. TwiML selects Relay language, but Twilio account is unconfigured. |
| Audible playback | **NOT IMPLEMENTED in browser** | No playback controls or audio output code in frontend. Provider-managed Relay audio was not exercised. |
| Persistence | **Verified for scripted simulator** | SQL Server contains the rows summarized below. Relay prompts are explicitly not persisted as transcripts by the router/service documentation. |

**Complete microphone-to-audible-response loop: No.** A distinct inbound telephony code path is present, but is configuration-blocked and has only simulated protocol tests.

### Console controls: wired, but not browser-verified

The controls are not just decorative in source: the Call Console buttons invoke `POST /api/demo/persona/{persona}` and `POST /api/demo/run-suite`; Customer Management calls customer, import, and verification routes; Call History calls call, outcome, callback, transcript, and summary routes; Analytics calls `GET /api/reports/calls` and `GET /api/reports/calls.csv`; Settings requests `GET /api/providers/status`. The frontend attaches its in-memory bearer token after login. I confirmed these handlers and the backend demo path separately, but did not sign into or click through the browser UI. The Console has no free-form conversation input or live session controls, so its “start” control starts a scripted backend persona, not a microphone conversation.

The optional telephony routes are `POST /api/twilio/voice`, `WS /api/twilio/relay`, and `POST /api/twilio/complete` in `service/app/routers/twilio.py`. They are not browser microphone routes and are not configured in the running environment.

## D. Database evidence

Read-only queries ran inside the running backend container. No inserts, updates, deletes, migrations, or reseeding occurred during this audit.

| Check | Observed result |
|---|---|
| SQLAlchemy dialect | `mssql` |
| Alembic revision | `0008_provider_sid_index` |
| Customers | 10 |
| Calls | 10; all 10 marked simulated |
| Call state | 8 completed, 2 failed (the failed ones are the scripted not-connected cases) |
| Outcomes | `right_customer` 2; `wrong_number` 2; `callback_requested` 2; `verification_failed` 2; `not_connected` 2; `third_party_answered` 0 |
| Transcript segments | 36; not-connected calls have no transcript |
| Summaries | 8; all 8 have exactly three lines; not-connected calls have no summary |
| Callback follow-ups | 2; both pending; both have `scheduled_at IS NULL` |
| Verification events | 0, although 2 right-customer and 2 verification-failed demo call outcomes exist |
| Volumes | `shaha_finlease_assignment_sqlserver_data` and `shaha_finlease_postgres_data` both remain present |

Direct calls to the read-only `dashboard_analytics`, `call_report`, and `export_call_report` handler functions against the running SQL Server session returned:

- Dashboard: 10 customers, 10 calls, 0 successful verifications, 2 callback requests (2 pending, 0 scheduled), 2 failed connections, and the outcome counts above.
- Report: 10 total calls, 8 connected, 2 not connected, 80.0% connect rate, 25.0% right-party rate, 0 verification successes/failures, 2 callbacks requested (2 pending, 0 scheduled).
- CSV: 10 data rows; header is `call_id,customer_reference,direction,status,outcome,started_at,ended_at,duration_seconds,callback_requested`.

Thus call totals/outcome totals reconcile. The persisted records reveal two real mismatches:

1. The two scripted callback results include a computed tomorrow-at-4-PM time in `run_persona`, but SQL Server shows both follow-ups still `pending` with no scheduled time. In `_save_demo_call`, `record_call_outcome` adds a pending callback and then a query tries to find it before the session flushes. The configured `SessionLocal` has `autoflush=False`, so the new row is not found and the schedule update is skipped.
2. The demo’s injected verification results only set call outcomes. They do not create `VerificationEvent` rows or update the customer’s verification state. Consequently, verification-event reports/dashboard customer verification counts will not reflect the simulated verification outcomes. The report query uses `VerificationEvent`, and dashboard success counts use `Customer.verification_status`.

All eight respondent summaries satisfy the exact three-line constraint. No missing summary or transcript discrepancy was found for the ten suite calls. The audit invoked handler functions directly with a live SQL Server `Session`, so it verified SQL dialect compatibility and aggregate/export logic without changing rows. It did not exercise the HTTP routing/authentication or signed-in browser UI: the backend container lacks `httpx` for its FastAPI `TestClient`, and no administrator password/token was read or exposed.

The SQL Server overlay adds a separate volume and the original PostgreSQL volume remains listed. No volume/container deletion or PostgreSQL reset was performed.

## E. Test and runtime evidence

Executed for this audit:

| Command/check | Result |
|---|---|
| `docker run --rm --network none shaha-finlease-backend-test sh -c 'python -m pytest -q && ruff check app tests migrations'` | **113 passed**, one upstream Starlette deprecation warning; Ruff: **All checks passed**. This is an isolated unit/API test image with no database network. |
| `npm run lint` in `voicebot/` | Passed (ESLint exit code 0). |
| `npx tsc --noEmit` in `voicebot/` | Passed (exit code 0). |
| `npm run build` in `voicebot/` | Passed; Next.js production build completed. |
| `GET http://localhost:8000/api/health/ready` | `ready`, database `connected`. |
| `GET http://localhost:3000` | HTTP 200. This checks page serving only, not authenticated browser operation. |
| Docker service status | `backend` up; PostgreSQL healthy; `frontend` up; SQL Server healthy. |
| SQL Server read-only aggregate queries | Results in section D. |

**Test limits:** `test_api.py`, `test_customer_workflows.py`, `test_outbound_safety.py`, `test_call_records.py`, and related tests primarily use dependency overrides/fake sessions; they do not constitute SQL Server API integration coverage. `test_migration.py` does not exercise the live SQL Server migration. `test_conversation.py`, `test_demo.py`, and `test_twilio_relay.py` exercise deterministic code or simulated protocol messages. There are no real microphone, browser voice, actual Hindi/English speech, TTS playback, real Twilio, or latency tests. SQL Server migrations and the prior ten-call smoke run were performed in the earlier implementation work; this audit independently checked current dialect/revision and persisted counts with read-only queries.

## F. Prioritized remaining work

### P0 — Required for a genuine voice demo

- Implement a browser or provider voice path end-to-end: microphone/audio input, real STT, turn transport, response generation, real TTS, playback, and user-visible errors/cancellation.
- Decide and configure an actual conversational model, with verified policy/verification boundaries. The current app is keyword routing and fixed scripts.
- Add browser end-to-end tests using real or controlled microphone/audio fixtures and measure actual utterance-end-to-audible-response latency. Do not claim the under-three-second target until measured.
- Exercise the authenticated console against SQL Server in a non-destructive integration test and compare dashboard/report/export responses with stored rows.

### P1 — Assignment, compliance, and persistence gaps

- Fix callback schedule persistence for the local persona runner and add a SQL Server regression test.
- Define how simulated identity verification should populate verification audit/report data, then ensure event and dashboard counts reconcile.
- Add and persist a third-party-answered-without-callback scenario; distinguish its outcome from a requested callback in the Console demo.
- Make opt-out durable/auditable and prevent ordinary customer edits/imports from clearing a DNC request without a documented authorized process.
- Tighten calling-window checks to exact time precision if the 19:00 inclusive boundary means only the instant 19:00:00, then test sub-minute boundaries.
- Add SQL Server integration coverage for migrations, callbacks, filters, metrics, export, and persistence. Current automated backend suite is not a SQL Server integration suite.

### P2 — Useful refinements

- Add language/simulation filters and any required latency dimensions to reports after real events exist.
- Add UI interaction tests for loading, API failures, auth expiry, accessibility, and responsive layouts.
- Inspect deployment access logging and provider-side data retention before any real customer traffic.
- Reconcile stale statements in `docs/ASSIGNMENT_CHECKLIST.md` and `docs/PROJECT_AUDIT.md` with current SQL Server evidence and this audit. They contain earlier or inconsistent verification notes.

## G. Final verdict

**READY FOR SIMULATED DEMO ONLY.** The local simulator, persisted SQL Server records, and operator-facing pages are demonstrable. The ten-record suite, summaries, transcript rows, SQL Server connection, and build/test checks have evidence. Callback schedule persistence and verification analytics do not reconcile fully.

**NOT READY FOR LIVE DEMO.** The browser has no microphone/STT/LLM/TTS/playback loop, Twilio Relay is unconfigured and was not tested against a real provider, and there is no actual latency measurement. The `localhost:3000` HTTP 200 is not evidence that an authenticated operator journey or voice call works end to end.

## H. Implementation update (2026-11-01)

This section supersedes the earlier implementation-gap statements where the corresponding code below has since been added. It does not supersede the old read-only SQL Server snapshot in section D: the Docker SQL Server engine was unavailable during this implementation pass, so that snapshot was not rechecked and migration `0009_browser_voice_safety` was not applied.

| Area | Updated status | Current evidence / limit |
|---|---|---|
| Browser microphone, local speech recognition, response playback, interruption, silence timeout and typed fallback | **IMPLEMENTED BUT NOT VERIFIED** | Added `voice-session.tsx` using `getUserMedia`, on-device `SpeechRecognition.processLocally`, and browser `speechSynthesis`; requires supported Chrome and installed language packs. No actual browser/microphone run occurred. |
| Conversational model | **BLOCKED BY MISSING CONFIGURATION** | Optional Gemini generic-small-talk adapter is gated by `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`; no key was configured or request made. Safety-critical flow remains deterministic. |
| Callback and verification reconciliation | **IMPLEMENTED BUT NOT VERIFIED** | Scheduled persona callback now inserts schedule at creation. Scripted/browser verification events link to calls and are reported as events; simulation does not modify operational customer verification status. SQL Server counts were not re-read. |
| Third-party no-callback | **IMPLEMENTED BUT NOT VERIFIED** | Added distinct scripted persona and Console option. Automated persona test added. |
| DNC auditing and release control | **IMPLEMENTED BUT NOT VERIFIED** | Added DNC event table/API, reasoned release action, and UI. Migration and SQL Server behavior were not exercised. |
| Exact calling-window boundary | **IMPLEMENTED AND VERIFIED** | Helper uses full local time precision; unit test cases include `19:00:00` and later instants. Outbound remains disabled. |
| Browser timing | **PARTIALLY IMPLEMENTED** | Persists client lifecycle timestamps and derived speech-synthesis-start latency. There are no real samples and this is not acoustic output measurement; the under-three-second goal is not verified. |
| Existing SQL Server records and additive migration | **PARTIALLY IMPLEMENTED** | Migration exists but was not run. Existing ten call rows from the prior audit remain the last known baseline, not a current-session observation. No reset, reseed, volume deletion, or record mutation was performed here. |

The application’s browser voice path is now coded, but the project is not ready to claim an end-to-end voice demo until migration `0009` is applied on the intended database, existing row counts are checked before/after, and a signed-in Chrome session is exercised. No model provider or real phone-call behavior is claimed as active.
