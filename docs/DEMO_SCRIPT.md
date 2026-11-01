# Ten-minute evaluator demo

This is a local, fictional-data demonstration. It does not place a telephone call. Use the administrator account configured locally; do not display its credentials.

| Time | Action | What to show |
|---|---|---|
| 00:00–00:45 | Sign in and show Overview. | Database-backed totals, outcome cards, DNC count and recent calls. If SQL Server is unavailable, state that the current page is not connected to the required database. |
| 00:45–01:30 | Open Customers and locate `DEMO-0005`. | Fictional customer record. Do not show verification factors in this screen. |
| 01:30–02:00 | Retrieve the evaluator fixture using the administrator-only lookup described in `API.md`. | It returns only the selected `DEMO-` record's name and birth year. Keep the response off-screen after the check. |
| 02:00–03:00 | Open Call Console and start the typed/browser voice simulation in English. | Automated-assistant and transcript disclosure, microphone permission handling, supported-browser message, and typed fallback. |
| 03:00–04:15 | Submit the known correct name and birth year in one utterance. | Verification result, redacted transcript answer, linked verification event, and safe post-verification boundary (no financial details). |
| 04:15–05:00 | Start another session and provide incomplete details, then the missing factor; optionally try an incorrect factor. | Only missing factor is requested; at most two attempts; no answer appears in transcript. |
| 05:00–06:00 | Demonstrate Hindi typed input, switch back to English, and play a synthesized response if supported. | Rule-based bilingual response and browser support/fallback. This is not a Hindi ASR quality claim. |
| 06:00–07:00 | Demonstrate wrong number and third-party-without-callback paths. | No customer data disclosure and distinct outcomes. |
| 07:00–08:00 | Demonstrate callback requested and provide an explicit future India time if prompted. | Callback stays pending when no supported explicit time was parsed; scheduled callbacks preserve time zone, reason and status history. |
| 08:00–09:00 | Open Call History and inspect a saved call. | Outcome, status, transcript provenance, three-line summary, callback history. Show the six outcome filters and date/customer filters. |
| 09:00–09:40 | Open Analytics and export the CSV. | Saved-record aggregates and allowlisted CSV columns. |
| 09:40–10:00 | State limitations and show test report. | Browser microphone requires a real browser check; no configured LLM/Twilio; no <3 second acoustic latency claim; SQL Server migration state must be confirmed on the running required stack. |

The **Run all six outcomes twice (12 calls)** simulator action is the repeatable database fixture if additional reporting rows are needed. It appends rows atomically; every use creates twelve more calls. Do not run it just before a strict record-count comparison.

## Reproducible demo factors

For the fictional seeded customer `DEMO-0005`, use the administrator-only fixture endpoint documented in `API.md`; the known fixture is **Demo Customer Five, 1990**. The ordinary customer screen and call UI do not show the year. The endpoint is rate-limited, requires admin authentication, and accepts only fictional `DEMO-` records.

## Safe setup

Follow [SETUP.md](SETUP.md) to bring up Docker Compose with both the base and SQL Server overlay files. Do not run `docker compose down -v`, reset the database, or use real customer data. Confirm migration revision and record counts using the documented read-only queries before presenting.
