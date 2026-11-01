# Project audit

## Current implementation review (2026-10-31)

The project is an existing Next.js admin UI, FastAPI service, and PostgreSQL database. Customer CRUD/import/verification, call records/outcomes, callback follow-ups, reports, protected transcript/summary reads, and retention helpers predate this audit update. These are covered by the existing API and workflow tests; API tests mostly use isolated fake sessions, while the configured database is checked separately with Alembic.

### Provider inventory

| Area | Existing interface or implementation | Verified status |
| --- | --- | --- |
| STT | `SpeechToText` protocol and marked mock adapter | No real STT provider configured. Mock output is a placeholder, not a transcript. |
| LLM | `LanguageModel` protocol and marked mock adapter | No real LLM configured. Deterministic conversation routing does not call a model. |
| TTS | `TextToSpeech` protocol and marked mock adapter | No real TTS configured. Mock bytes are not speech audio. |
| Telephony | `Telephony` protocol, `SafeDevelopmentTelephony`, signed Twilio Conversation Relay adapter | Twilio inbound webhook/WebSocket adapter is implemented but is unconfigured unless backend secrets and a public HTTPS origin are supplied. No outbound dialing capability is implemented. |
| Orchestration | `ConversationOrchestrator` protocol, `ConversationEngine`, `TwilioRelaySession` | Hindi/English deterministic text routing is connected to Relay prompts. The adapter does not persist caller utterances. Voice identity verification is deliberately unavailable without a trusted customer binding. |
| Call analysis | `CallAnalysis` protocol and marked mock adapter | No real analyzer configured. Summary retry reports `provider_unconfigured`. |

All provider outputs are explicitly tagged with provenance and simulation state in mock adapters. Provider timeout/retry helpers cap attempts at three and propagate final errors. The provider status endpoint/UI exposes only readiness flags, never credential values.

### Verified workflows and current limits

- Customer create/update/import, identity verification privacy, verification rate limiting, auth protection, report export allowlists, callback model safeguards, conversation behavior, provider timeout handling, and persistence restrictions have automated tests.
- Callback requests create one active follow-up per call and retain status history. Call outcomes and callback scheduling use the existing protected API.
- Call status can now transition once from queued to completed, failed, or disconnected. Lifecycle events are persisted and administrator-only. These are operational/admin states, not proof of a connected telephone call.
- Transcript and summary persistence helpers reject simulated calls and require provenance. The API hides expired content. No live transcription/summary pipeline is installed.
- The conversation engine supports English/Hindi selection and switching, deterministic intents, verification handoff, wrong-number/third-party termination, callback/human escalation, unclear input handling, structured outcomes, and safe provider errors. Twilio Conversation Relay connects signed inbound voice sessions to the engine; no account credentials, public endpoint, paid setup, or real call were used for this implementation.
- Relay request signatures use Twilio's official Python SDK validator against the configured canonical URL. Protocol tests use an injected validator and simulated WebSocket sessions. Public HTTPS/WSS reachability and real Twilio account behavior remain unverified.
- Customer/call/report routes require the single configured administrator bearer token. There is no financial-disclosure endpoint. Verification does not authorize financial disclosure.
- Outbound call workflows remain disabled by default. Consent, do-not-call, and local calling-hour checks gate outbound operational record creation when enabled; eligibility never dials.

### Tests and environment checks

The current implementation and verification results are summarized in [TEST_REPORT.md](TEST_REPORT.md) and [ASSIGNMENT_CHECKLIST.md](ASSIGNMENT_CHECKLIST.md). Most backend unit tests use SQLite or fakes, with a separate preserved-volume SQL Server run documented in the test report. Never reset the named database volume to resolve a migration issue.

The `voicebot/` directory contains the existing Git metadata; the project root is not itself a Git worktree. Keep `.env`, credentials, and database volumes intact. No changes are committed or pushed by this audit.

## Historical initial audit

The initial scaffold audit (2026-10-30) found only a Create Next App interface and no backend, Compose setup, or testable API. That was a historical snapshot; the application described above has since been implemented and expanded. Its initial environment limitations are no longer current and should not be used as the present readiness assessment.

## Browser voice implementation update (2026-11-01)

An authenticated browser simulation now uses local-only Web Speech Recognition where the browser exposes `processLocally`, browser speech synthesis, typed fallback, 15-second silence closure, multi-turn deterministic handling, verification redaction, and timing persistence. The optional Gemini adapter is disabled by default and limited to allowlisted generic small talk. The callback schedule insertion bug, simulated verification event discrepancy, third-party no-callback persona, and ordinary DNC clearing gap have code/test coverage. The calling window now checks the exact 19:00:00 boundary.

Historical note: an earlier audit could not reach Docker and therefore did not verify SQL Server migration or authenticated browser operation. In the 2026-11-01 completion pass, the existing SQL Server stack was started, migration `0010_voice_turn_idempotency` was applied, an append-only fictional scenario suite and one text-only browser simulation were run, and counts/analytics/export were checked. Browser microphone, audible playback, Gemini, and Twilio remain untested/unconfigured; existing volumes were preserved and no real phone call was placed.
