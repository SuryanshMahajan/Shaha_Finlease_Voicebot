# Browser Voicebot Completion Plan

This plan maps the implementation brief to the existing application. It preserves the current Next.js/FastAPI structure, authentication, SQL Server and PostgreSQL Compose paths, and existing database rows.

## Preservation constraints

- Keep `.env` unchanged and never print its contents.
- Keep both named database volumes and all existing customer/call records. Use only additive schema migrations; do not reset, reseed, or rerun the ten-call smoke suite.
- Keep outbound calling disabled and do not configure or call Twilio.
- Keep scripted personas available as a separate, clearly labeled demo mode.
- Keep real identity decisions in backend code; redact verification answers from transcript, logs, model context, and provider errors.
- Keep the LLM optional. Use the deterministic backend flow when no free-tier Gemini key is explicitly configured.

## Requirement-to-file plan

| Requirement | Planned implementation files |
|---|---|
| Browser voice session, Chrome Web Speech recognition, browser speech synthesis, text fallback, listening/processing/speaking/ended states, interruption and error recovery | `voicebot/src/app/call-console.tsx`, new `voicebot/src/app/voice-session.tsx`, new `voicebot/src/lib/browser-voice.ts`, `voicebot/src/lib/api.ts`, `voicebot/src/app/globals.css` |
| Persisted live browser session, backend-owned intent/verification/state decisions, multi-turn context, transcript redaction and three-line completion summary | New `service/app/services/browser_voice.py`; `service/app/services/conversation.py`; `service/app/main.py`; `service/app/services/call_records.py`; `service/app/models/entities.py`; `service/app/schemas/api.py` |
| Additive SQL Server/PostgreSQL schema for session channel/state, per-turn latency samples, verification-to-call linkage, and durable DNC audit events | New `service/migrations/versions/0009_browser_voice_safety.py`; `service/app/models/entities.py`; `service/tests/test_migration.py` |
| Correct callback schedule persistence, verification events, third-party-without-callback outcome, and immutable DNC by default with explicit authorized release | `service/app/main.py`; `service/app/services/call_records.py`; new `service/app/services/browser_voice.py`; `service/app/models/entities.py`; `service/app/schemas/api.py`; `voicebot/src/app/customer-management.tsx`; related backend tests |
| Exact 08:00:00–19:00:00 Asia/Kolkata limits | `service/app/services/outbound.py`; `service/tests/test_outbound_safety.py` |
| Optional LLM interface and free-tier-only Gemini adapter, fixed deterministic fallback, prompt/PII boundaries | New `service/app/services/llm.py`; `service/app/core/config.py`; `service/app/main.py`; `service/tests/test_llm.py`; `.env.example` and Compose environment pass-through only (never `.env`) |
| Actual browser lifecycle latency, per-turn and aggregate API/UI metrics | New `VoiceTurnMetric` model in `service/app/models/entities.py`; migration 0009; `service/app/main.py`; `service/app/schemas/api.py`; `voicebot/src/lib/browser-voice.ts`; `voicebot/src/app/voice-session.tsx`; report/API types and docs |
| Browser/API test coverage and SQL Server integration coverage | `voicebot` browser helper tests/config and `voicebot/src/app` test files; new backend tests under `service/tests/`; SQL Server migration/integration test command documented in `docs/SETUP.md` |
| Setup, safety disclosures, API behavior, prompt rules, demo script, verification status | `README.md`, `docs/SETUP.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/BOT_PROMPT.md`, `docs/ASSIGNMENT_CHECKLIST.md`, `docs/VOICEBOT_AUDIT_REPORT.md` |

## Delivery order

1. Preserve a read-only baseline: confirm the running dialect, schema revision, and existing synthetic row counts; inspect current source and tests.
2. Fix persistence/state rules and add additive migration plus backend tests before exposing new routes.
3. Add the optional LLM boundary with strict data minimization and no default provider configuration.
4. Add authenticated browser voice session/turn/end/latency APIs and deterministic fallback.
5. Add the voice UI and browser API/error/latency tests while preserving the persona runner.
6. Apply only the additive migration to the already-active SQL Server, verify the old ten calls remain, and add new records only through an explicitly started browser session.
7. Run backend tests, SQL Server integration checks, frontend lint/typecheck/build, and any available browser tests. Report microphone, audible playback, LLM, and latency as unverified unless they are actually exercised.
8. Update the listed documentation with exact capabilities, prerequisites, privacy behavior, and a revised ten-minute demo.

## Acceptance checks

- A browser session requires user-started microphone permission, identifies support failures clearly, and has a labeled text fallback.
- Browser speech turns go to an authenticated backend route; no identity decision is made in the browser or by a model.
- Hindi and English turn text and speech voice selection are supported; transcripts preserve turn order/timestamps and redact verification factors.
- All six call outcomes have explicit backend transitions; third-party-without-callback is independently testable.
- Callback schedules, verification events, DNC audit history, and metrics reconcile on SQL Server.
- DNC cannot be cleared by ordinary edit/import; any release is a separately authorized, reasoned, audited action.
- The call window rejects times after exactly 19:00:00 Asia/Kolkata.
- Per-turn latency derives from speech-end and browser speech-start events; no hardcoded latency values are reported.
- Existing customer/call records and both database volumes remain intact; no real telephony or paid API use occurs.

## Provider investigation

As checked on 2026-11-01, Gemini Developer API pricing lists free input/output for eligible Gemini 3.5 Flash-Lite projects; quotas depend on model/project and are visible in AI Studio. Google states that free-tier submitted content may be used to improve its products, and not all projects/accounts are eligible. Therefore the adapter will be optional and disabled by default, will not receive customer records or verification factors, and must only be enabled with an explicitly free-tier project that has no billing configured. No provider credentials or real API test are available for this implementation.

Sources: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing), [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits), [Web Speech API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Speech_API), [Chrome on-device speech recognition](https://developer.chrome.com/blog/new-in-chrome-139/).

## Implementation status

Implemented in this revision: browser session routes and UI, typed fallback, on-device speech mode requirement, safety state-machine turns and retries, transcript redaction, measured timing persistence/report aggregates, callback schedule correction, linked verification events, separate third-party no-callback scenario, DNC event/release workflow, exact calling-window boundary, and documentation updates. Backend tests, Ruff, frontend lint, TypeScript, and production build pass.

Completed after this plan was drafted: SQL Server was started on the preserved volume, migration `0010_voice_turn_idempotency` was applied, prior customer/call rows were preserved, all six outcome paths were persisted, and authenticated dashboard/report/export plus a text-only browser voice flow were verified. Still unverified: a fresh SQL Server volume migration, signed-in Chrome with a physical microphone and language packs, acoustic playback, Gemini request, Twilio, and actual latency samples. See [TEST_REPORT.md](TEST_REPORT.md) for exact counts and commands.
