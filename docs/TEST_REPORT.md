# Test report

Updated 2026-11-01. Results below are commands executed in this workspace; they do not establish SQL Server or real-browser behavior.

## Automated checks

| Check | Result |
|---|---|
| `cd service; .\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | **138 passed**, one upstream Starlette/AnyIO deprecation warning. |
| `cd service; .\.venv\Scripts\ruff.exe check app tests migrations` | **All checks passed.** |
| `cd voicebot; npm run lint` | **Passed**, exit 0. |
| `cd voicebot; npx tsc --noEmit` | **Passed**, exit 0. |
| `cd voicebot; npm run build` | **Passed**, Next.js production build completed. |
| `cd service; .\.venv\Scripts\alembic.exe heads` | **0010_voice_turn_idempotency (head)**. The SQL Server's applied revision was independently checked as the same. |

Tests cover deterministic English/Hindi conversation paths, combined and partial verification factors, failed attempts, factor redaction, duplicate-turn idempotency, twelve simulated calls covering each of six outcomes twice using SQLite, callback validation/persistence helper, DNC release controls, API authorization, summary length, dashboard/report aggregation, CSV header and row count, migration structure, browser session handlers using SQLite, and voice metrics validation.

## SQL Server verification

- `docker compose -f docker-compose.yml -f docker-compose.sqlserver.yml up --build -d backend frontend sqlserver` completed; SQL Server and PostgreSQL reported healthy, backend/frontend were running, backend readiness returned `ready` / `connected`, and the frontend returned HTTP 200.
- Applied revision: `0010_voice_turn_idempotency`; SQLAlchemy dialect: `mssql`.
- Before demo inserts: 10 customers and 14 calls. After running the existing six-outcome suite twice and one text-only browser simulation: 10 customers and 27 calls. All six outcomes are present at least twice: right customer 6, wrong number 4, third party 2, callback requested 4, verification failed 4, not connected 4.
- SQL Server has 103 transcript messages and 21 summaries; every stored summary has exactly three lines. Callback status counts are 2 pending, 2 scheduled, 0 completed. Seven verification events are present. One browser turn idempotency record was persisted.
- Final authenticated dashboard and report totals both matched SQL Server at 27 calls; all outcome counts matched. The CSV contained 27 data rows with the expected allowlisted header. The final report showed five successful and two failed verification events. The text-only browser session was confirmed as a right-customer result, replay-safe, factor-redacted, event-linked, completed, and summarized in three lines.

## Not run / blocked

- No real Chrome/Edge microphone session, browser language pack, acoustic audio playback test, interruption test, speech-recognition device error test, or latency sample was produced. The admin UI was not manually clicked through in a browser; authenticated API routes were exercised directly.
- No Gemini or Twilio credentials/provider request was used. No real or outbound call was placed.
- No DB reset, drop, truncate, reseed, or `.env` opening/editing/printing was performed. The backend's configured authentication settings were used in-process to issue short-lived tokens for protected API verification; no secret value or token was printed, saved, or changed.

## Re-run commands

From the repository root:

```powershell
Set-Location service
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\.venv\Scripts\ruff.exe check app tests migrations
.\.venv\Scripts\alembic.exe heads
Set-Location ..\voicebot
npm run lint
npx tsc --noEmit
npm run build
```

For the SQL Server stack, first ensure Docker Desktop is running and the local SQL Server password is configured without printing it, then follow the combined Compose command in `SETUP.md`. Verify health and current Alembic revision and compare read-only customer/call counts before and after migration. Preserve both named volumes.
