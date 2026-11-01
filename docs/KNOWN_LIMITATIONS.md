# Known limitations

Updated 2026-11-01.

- The local SQL Server Compose stack is running and Alembic revision `0010_voice_turn_idempotency` is applied. This does not prove behavior on other SQL Server versions or deployment environments.
- Browser voice uses Web Speech APIs and browser-managed speech output. The code has typed fallback and error paths, but no real microphone/browser interaction was run in this session. Recognition language packs and Hindi pronunciation vary by browser and operating system.
- No acoustic response-start measurement exists. Stored browser timestamps measure recognition completion/request/response/synthesis-start according to the browser client; they do not prove audible sound began or that the three-second requirement is met.
- The conversational engine is deterministic and rule-based. Optional Gemini small talk is disabled by default and unconfigured. It is not used for verification or protected customer information.
- Twilio Conversation Relay code is optional and unconfigured. No provider request, live inbound call, outbound call, or public webhook test was made. No outbound dialer exists and outbound calling remains disabled.
- SQL Server integration was exercised against the preserved local volume, including migration, authenticated text-turn persistence, outcome suite, dashboard, report, and CSV export. The run began with 10 customers and 14 calls and ended with 10 customers and 27 calls; it appended 12 scripted outcome calls and one browser text simulation. SQL Server-specific production deployment behavior remains unverified.
- A migration from the existing `0009` SQL Server schema was exercised. A completely fresh SQL Server database/volume migration was not run because the instruction was to preserve existing volumes and records.
- A successful `speechSynthesis` start timestamp is not an acoustic audio measurement; no claim is made that spoken sound began or that the three-second target is met.
- `not_connected` outcomes are represented as failed terminal calls by the outcome persistence helper; busy, unavailable, unanswered, and browser silence are not yet distinct persisted reason codes.
- The simulator does not unlock financial disclosure after identity verification; the prototype has no financial-data endpoint.
