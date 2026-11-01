# Shaha Finlease Conversational AI Voicebot

A local assignment prototype with a Next.js operator dashboard, FastAPI backend, customer CSV import, Hindi/English deterministic conversation engine, scripted personas, and an opt-in browser voice simulation. Browser voice uses on-device Web Speech recognition where supported and browser speech synthesis; it remains a simulation and never dials. Outbound telephony is disabled.

## Local startup

Prerequisites: Docker Desktop with Compose v2, Node.js 22/npm 10 (only for frontend development outside Docker), and an administrator-configured local `.env` file. Never overwrite an existing `.env`. The PostgreSQL workflow preserves the existing `postgres_data` volume; the SQL Server assignment overlay uses a separate `assignment_sqlserver_data` volume.

For the assignment SQL Server path, configure a strong local `SQLSERVER_SA_PASSWORD` in `.env` and use:

```powershell
docker compose -f docker-compose.yml -f docker-compose.sqlserver.yml up --build -d backend frontend sqlserver
docker compose -f docker-compose.yml -f docker-compose.sqlserver.yml ps
Invoke-RestMethod http://localhost:8000/api/health/ready
```

The overlay binds SQL Server to `127.0.0.1:1433`, creates a separate `shaha_finlease` database, and applies Alembic migrations. Existing PostgreSQL data is neither copied nor deleted. To preserve the original PostgreSQL app path, use `docker compose up --build -d` instead. Stop either stack with `docker compose down` (without `-v`). Full prerequisites, auth setup, limitations, and troubleshooting are in [docs/SETUP.md](docs/SETUP.md).

Open the frontend at [http://localhost:3000](http://localhost:3000). Configure `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, and `JWT_SECRET` in `.env` as described in setup. No credential belongs in source control or chat.

## Demonstration data and workflow

Download/import [`data/example_customers.csv`](data/example_customers.csv), which contains ten clearly fictional test customers and dummy phone values. In the dashboard, open **Call Console**, choose a customer and persona, and start a simulated session. **Run all six outcomes twice** writes twelve simulated calls atomically (two per outcome). Open Call History to inspect saved transcripts, exactly three summary lines for calls with a respondent, callbacks, timestamps, and outcomes. Silence has no fabricated transcript or summary. Analytics are derived from saved database rows.

The Call Console retains its scripted personas and adds **Talk to the assistant**. Use current Chrome on `localhost` or HTTPS, grant microphone access, and install its on-device English or Hindi speech pack if prompted. Recognition is forced to local processing; the app does not silently fall back to an online recognizer. Browser speech synthesis plays responses and can vary by operating system. A typed fallback is available. The app stores recognized text, assistant replies, outcomes, and timing timestamps when supplied by the browser; it does not store microphone audio. Verification answer transcript entries are redacted. No phone call occurs.

An optional Gemini adapter handles generic small talk only when `LLM_PROVIDER=gemini` and `GEMINI_API_KEY` are explicitly configured. It is disabled by default, excludes obvious identity/account content, and falls back to deterministic responses. No Gemini key is configured by this repository. Free-tier eligibility and quotas vary, and free-tier prompts may be used to improve Google products; see [pricing](https://ai.google.dev/gemini-api/docs/pricing) and [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) before enabling it.

Migration `0009_browser_voice_safety` adds browser session state, verification links, DNC audit events, and voice timing samples. Migration `0010_voice_turn_idempotency` adds partial verification state, callback timezone/reason, and retry-safe browser turn results. Both are applied to the local SQL Server database (current revision `0010_voice_turn_idempotency`). SQL Server contained ten customers and fourteen calls before this turn's append-only demo run; it now has ten customers and twenty-seven calls after the twelve-call outcome suite and one text-only browser simulation. No existing records or volumes were reset.

## Main safeguards

- Outbound calling remains disabled; the UI simulator does not dial.
- Actual outbound workflow records require documented consent, no Do Not Call restriction, enabled configuration, and the Asia/Kolkata 08:00–19:00 window inclusive at 19:00.
- The conversation engine has explicit verification, wrong-number, third-party, callback, and opt-out transitions. Verification answers are passed to a verifier and are excluded from transcripts/logs.
- No financial disclosure endpoint exists. Customer APIs minimize sensitive fields.
- Simulated transcripts/summaries use `local_simulation` provenance; summaries contain exactly three lines. Missing respondents produce no transcript.
- Authentication protects administrative APIs; Twilio remains optional, inbound-only, signed, and unconfigured unless the owner supplies credentials.

## Documentation and checks

- [Setup and demo script](docs/SETUP.md)
- [API reference](docs/API.md)
- [Architecture and security](docs/ARCHITECTURE.md)
- [Bot policy and fixed prompt](docs/BOT_PROMPT.md)
- [Requirement checklist and verification status](docs/ASSIGNMENT_CHECKLIST.md)
- [Exact ten-minute demo sequence](docs/DEMO_SCRIPT.md)
- [Executed test report](docs/TEST_REPORT.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Project audit](docs/PROJECT_AUDIT.md)

Commands: `Set-Location voicebot; npm run lint; npx tsc --noEmit; npm run build`; `Set-Location ..\service; python -m pytest`. See the checklist for checks actually available in the current environment; unavailable test dependencies or SQL Server runtime are not represented as passing.
