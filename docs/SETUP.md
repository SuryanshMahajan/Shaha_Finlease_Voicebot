# Local setup (Windows PowerShell)

From the repository root. Docker commands assume Docker Desktop is installed and running. Never run `docker compose down -v` as routine cleanup; the named database volume is persistent.

## Assignment SQL Server workflow

The assignment requires SQL Server. The additive overlay uses a dedicated SQL Server container and the separate named volume `assignment_sqlserver_data`; it does not migrate PostgreSQL data. Keep the existing `.env` intact and add a strong `SQLSERVER_SA_PASSWORD` of at least 8 characters with upper/lowercase letters, a digit, and a symbol. Use characters that are URL-safe (for example, end with `!`) because the backend also uses the password in its SQLAlchemy connection URL. Do not paste the value into chat.

```powershell
docker compose -f docker-compose.yml -f docker-compose.sqlserver.yml up --build -d backend frontend sqlserver
docker compose -f docker-compose.yml -f docker-compose.sqlserver.yml ps
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/health/ready
```

The SQL Server port binds only to loopback. The backend creates `shaha_finlease` if absent and runs Alembic migrations before Uvicorn. The base PostgreSQL service may also start because the overlay extends the original Compose project; it remains an independent rollback path and its volume is not modified. Do not use `down -v`. SQL Server integration must be checked on the local Docker engine before the assignment demo; a Compose file alone is not evidence that SQL Server started. Use the combined two-file command above; the SQL Server file is an overlay and needs the base file's `internal` network definition.

For the exact evaluator walkthrough and the admin-only fictional verification fixture, see [DEMO_SCRIPT.md](DEMO_SCRIPT.md) and [API.md](API.md). Current environment results and limitations are recorded in [TEST_REPORT.md](TEST_REPORT.md) and [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Existing PostgreSQL workflow

```powershell
# Create .env only if it does not already exist; never overwrite local settings.
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Edit .env and replace POSTGRES_PASSWORD with a unique local development password.
docker compose up --build -d
docker compose ps
docker compose exec db pg_isready -U shaha_app -d shaha_finlease
Invoke-RestMethod http://localhost:8000/api/health
Invoke-RestMethod http://localhost:8000/api/health/ready
```

Compose waits for PostgreSQL health before starting the backend; its Compose command applies Alembic migrations before starting Uvicorn. This path is the existing PostgreSQL rollback configuration, not the SQL Server assignment database. Logs: `docker compose logs -f backend`. Stop services while preserving data: `docker compose down`.

## Local development processes

### Configure the local administrator

Administrative APIs fail closed until all three values are configured in the root `.env`: `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, and `JWT_SECRET`. Keep the password itself out of `.env`; store only its Argon2id hash. Generate a hash interactively from the project virtual environment (the password prompt does not echo input):

```powershell
Set-Location service
.\.venv\Scripts\python.exe -c "from getpass import getpass; from pwdlib import PasswordHash; print(PasswordHash.recommended().hash(getpass('Admin password: ')))"
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Use a unique passphrase of at least 14 characters. Copy the hash and generated random secret into the matching root `.env` entries, choose a local admin username, then rebuild/restart the backend. Use `/api/auth/login` with form fields `username` and `password`; the UI keeps the returned 30-minute bearer token in memory only and requires sign-in again after a page refresh. Never commit `.env` or share the generated values. The example file contains placeholders only.

Authentication is a single local administrator account, suitable for a development prototype rather than production account management. Authentication and verification attempt limits are per backend process and reset on restart; multiple workers/instances need a shared limiter store and trusted proxy IP configuration before deployment.

Outbound call workflows are disabled by default. Keep `OUTBOUND_CALLING_ENABLED=false` while no approved provider and operational safeguards are in place. If a future provider integration is approved, configure the IANA `CALLING_TIMEZONE` and `CALLING_HOUR_START` / `CALLING_HOUR_END` window. The current application only records an operational entry; it never dials. Customers need a recorded consent timestamp and evidence source and must not be marked do-not-call before an outbound workflow record can be created. CSV import never grants consent.

Callback requests create one pending or scheduled follow-up per call; an active follow-up cannot be duplicated. Follow-up notes are limited and should contain logistics only. Verification history records result and timestamp without submitted factors. Scripted and browser simulation transcripts use separate provenance; browser verification answers are redacted. Gemini small-talk support is optional and disabled by default.

The Twilio Conversation Relay inbound adapter connects signed Twilio webhooks and an authenticated Relay WebSocket to the deterministic Hindi/English engine. It accepts inbound calls only and does not persist Relay prompts as transcripts. Voice identity verification remains unavailable on this provider route because there is no trusted caller-to-customer mapping. Browser simulation voice is a separate local Web Speech path. The protected `/api/providers/status` endpoint and Settings screen show readiness without exposing secrets.

### Optional Twilio Conversation Relay configuration

The adapter is inactive unless all three backend settings are present. Add these to the existing root `.env` without replacing that file; `.env.example` contains blank placeholders only:

```dotenv
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PUBLIC_BASE_URL=https://voice.example.com
```

`TWILIO_PUBLIC_BASE_URL` must be the externally visible HTTPS origin (no path), and the backend must be reachable at `/api/twilio/voice`, `/api/twilio/complete`, and `/api/twilio/relay` over HTTPS/WSS. Twilio signature verification uses the exact configured public URL, so proxy routing and the Twilio webhook URLs must match it. Configure a Twilio Voice application to use `POST https://<origin>/api/twilio/voice`; the returned TwiML connects to `wss://<origin>/api/twilio/relay` and posts completion to `/api/twilio/complete`. Enable Conversation Relay on the Twilio account and assign the Voice application to an inbound number through Twilio Console. Those account/number actions may incur charges and are intentionally not performed here. Do not expose the auth token to the browser or logs. `OUTBOUND_CALLING_ENABLED` remains false and does not enable dialing.

Readiness distinguishes unconfigured, configured, and active Relay sessions. Configured does not mean a call has connected. A public HTTPS/WSS deployment, provider account setup, and inbound number assignment are still required before an approved pilot. No real call is needed for local mock tests.

## Render deployment draft

The repository includes a root [`render.yaml`](../render.yaml) Blueprint for the existing Dockerized Next.js frontend, FastAPI backend, and a private Render Postgres database. It is a cost-capped preview draft. Do not create these resources yet or use it for real customer data or a call pilot:

- The Blueprint pins all three resources to Render's Free plans so reviewing it cannot silently select paid compute. Free web services can spin down, and Free Render Postgres expires 30 days after creation; after the grace period Render deletes its data. These limits make the draft unsuitable for a controlled voice pilot or durable production records.
- Render runs `preDeployCommand` only on paid web services. Before any deployment, a workspace owner must explicitly approve an always-on backend plan and a durable database plan, then update the Blueprint. The migration command is `alembic upgrade head`; it runs once in Render's pre-deploy phase, not concurrently in each web instance. Do not deploy the draft while its backend is on the Free plan.
- The Free preview limits and the paid-plan migration prerequisite are deliberate blockers under the current no-purchase instruction. No Render resources have been created.

### Review and configure the Blueprint

1. Connect the Git repository to Render and choose **Blueprint** / `render.yaml`. Review the detected web services and Postgres resource before creating anything. The service names are `shaha-finlease-api`, `shaha-finlease-web`, and `shaha-finlease-db`; the proposed region is Singapore and should be checked against your data-residency requirements. Keep automatic deploys off until a deployment workflow is approved.
2. Do not deploy using the Free plans. For a future pilot, first choose acceptable always-on backend and durable Postgres plans in the Blueprint/Dashboard. Render documents pre-deploy commands for paid web services; the Blueprint's migration runs before app startup. Database migrations should be reviewed as forward-compatible and the data backup/restore plan agreed before deploying.
3. Render connects services to Postgres through the database's private `connectionString` reference. The Settings validator adapts Render's `postgresql://` URL to the pinned psycopg 3 driver. Postgres has `ipAllowList: []` and no public port; do not add an external database URL or public allowlist.
4. Once Render assigns the service URLs, verify the actual hostnames. Update `NEXT_PUBLIC_API_URL` on the frontend to `https://<backend-host>/api` and `CORS_ORIGINS` on the backend to the exact `https://<frontend-host>` origin if the generated names differ from the Blueprint defaults. Save and rebuild the frontend so Next.js embeds the correct public API URL. The frontend variable is public and must never contain credentials.
5. In the backend service's Environment page, manually configure `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH`, and `JWT_SECRET`. Generate the password hash locally using the existing setup instructions; enter only the hash and a separately generated secret into Render's protected environment interface. Do not use values from `.env` or copy that file into Render.
6. Leave `OUTBOUND_CALLING_ENABLED=false`. Only after a public backend HTTPS URL exists, add `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PUBLIC_BASE_URL` in the backend's protected environment settings. `TWILIO_PUBLIC_BASE_URL` is the HTTPS origin only, such as `https://<backend-host>`; it must match the externally visible webhook host. Twilio credentials remain backend-only.
7. Render terminates TLS for web services; use `https://<backend-host>/api/health` and `/api/health/ready` to check health. Set the Twilio Voice application webhook to `POST https://<backend-host>/api/twilio/voice`. The returned TwiML uses `wss://<backend-host>/api/twilio/relay`; Twilio sends completion to `/api/twilio/complete`. Render web services support WebSocket connections. Verify the public HTTPS and WSS routes before associating an inbound number.

The backend does not trust forwarded host/protocol headers to construct Twilio signature URLs. It uses the configured canonical `TWILIO_PUBLIC_BASE_URL` and request path, avoiding reliance on client-supplied proxy headers. Health routes reveal only liveness/database readiness; provider readiness remains administrator-protected and omits secrets. The frontend and API use the exact configured CORS origin; do not use `*`.

### Rollback and persistent data

Use Render's prior successful application deploy to roll back code. Keep the managed Postgres resource and its data in place; never delete it as part of an application rollback. The migration is a pre-deploy step and may have already advanced the schema even if the app deploy fails, so do not automatically downgrade the schema. Review migration compatibility and the provider's backup/restore options before the first database migration. No local Compose data is included or uploaded by this Blueprint.

Transcript segments and summaries expire after `TRANSCRIPT_RETENTION_DAYS` (default 180 days). Expired content is hidden by the API. Schedule this cleanup command according to your retention policy; it deletes expired content while preserving call records and metadata:

```powershell
docker compose exec backend python -m app.services.retention
```

The identity-verification status only records completion of the name and birth-year check. It does not authorize access to financial information. No financial-disclosure API is implemented. Existing legacy rows without birth year remain unverified.

Start PostgreSQL only with `docker compose up -d db`. The host port is `127.0.0.1:5432` by default. In one PowerShell window:

```powershell
Set-Location service
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
$env:DATABASE_URL = "postgresql+psycopg://shaha_app:replace-with-a-local-password@localhost:5432/shaha_finlease"
$env:CORS_ORIGINS = "http://localhost:3000"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another window:

```powershell
Set-Location voicebot
npm ci
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000/api"
npm run dev
```

Open `http://localhost:3000`. If Python has no pip, install/repair the official Python installation or use the Docker workflow. Never paste production credentials into source files.

## Quality checks

```powershell
Set-Location voicebot
npm run lint
npx tsc --noEmit
npm run build
Set-Location ..\service
python -m pytest
ruff check app tests migrations
```

## Ten-minute demonstration

1. Open `http://localhost:3000` and sign in with the local administrator account.
2. In Customers, import `data/example_customers.csv`; confirm ten fictional records and the preferred languages/DNC flags.
3. Open Call Console and show the simulation label and consent/DNC eligibility. Attempt a real outbound workflow only as a blocked configuration demonstration; outbound calling is disabled and no phone call is placed. The application reports the Asia/Kolkata window as 08:00–19:00 inclusive when the workflow is enabled for controlled tests.
4. Run the Hindi right-customer persona; show simulated disclosure, redacted verification input, transcript, outcome, and three-line summary.
5. Run wrong number and third-party callback personas; confirm no customer-specific details are spoken to the third party.
6. Run incorrect birth-year verification and silence. Silence has no transcript because nobody responded.
7. Select **Run all six outcomes twice (12 calls)**; expect twelve new persisted simulated attempts, two for every outcome. Open Call History and inspect outcome, language, duration, saved transcript, summary, and callback.
8. Open Analytics and compare outcome totals with Call History. Demonstrate the dashboard is database-backed. Browser timing samples, when present, measure from utterance-end to speech-synthesis-start; do not claim the three-second target is achieved without measured results.
9. In Customers, demonstrate the DNC flag and attempt the local persona; backend returns a clear blocked message. The backend also rejects outbound attempt creation for opted-out records.
10. In Settings, show provider readiness as configured/unconfigured/simulated. Twilio is not configured. Browser speech is not a telephony integration; Gemini remains disabled unless explicitly configured.

For a direct local API demo, sign into the dashboard first, then use the call console controls. No manual database edits or undocumented APIs are required.

### Browser voice simulation

Use current Chrome from `http://localhost:3000` (or HTTPS). Select **Talk to the assistant**, choose one of the fictional demo customers and English or Hindi, and select **Start browser voice simulation**. Grant microphone permission. This application requires the browser's `processLocally` speech recognition mode; if a language pack is missing, Chrome reports an error and the visible typed fallback remains available. It never falls back to online recognition automatically. Browser speech synthesis may use device-specific voices and is not an acoustic latency measurement. The session is simulated, stores recognized text/replies, redacts identity-answer turns, and does not store audio or place a call.

Migrations through `0010_voice_turn_idempotency` are applied to the local SQL Server instance and the readiness route reports the database connected. The authenticated browser microphone flow has not been manually tested. Keep any later schema changes additive; do not reset or reseed an existing database. The current verification run preserved the ten customer rows and appended only the documented twelve-call suite and one text-only browser simulation.

Gemini is disabled by default. Enabling it requires explicitly setting `LLM_PROVIDER=gemini` and supplying `GEMINI_API_KEY` through a protected local environment. The adapter only accepts generic small talk after local filtering; do not supply real customer data. Review current provider quota and data-use terms before configuring.

Optional local persistence smoke run (development only): `docker compose -f docker-compose.yml -f docker-compose.sqlserver.yml exec -T backend python -m app.scripts.smoke_demo`. It parses the same fictional CSV, inserts only missing `DEMO-` customers without clearing existing DNC flags, runs all six outcomes twice, and checks that twelve call rows plus valid summaries persist. It never dials. Running it again adds another twelve labeled simulation rows.

These commands are documented; the audit report records which could be run in the implementation environment.

## Reset development database (destructive)

This permanently removes local PostgreSQL data. Stop containers and explicitly remove the volume only when you intend to erase the development database:

```powershell
docker compose down
docker volume ls
# Inspect the exact Compose volume name, then run only after confirming it is the development volume:
docker volume rm shaha_finlease_postgres_data
```

## Common issues

- **Connection refused:** verify Docker Desktop and `docker compose ps`; local backend uses `localhost`, Compose backend uses `db`.
- **Password authentication failed:** keep the same `.env` password used when the named volume was first initialized. Changing the env value does not rewrite an existing database user's password.
- **Port already in use:** change `POSTGRES_PORT`, `BACKEND_PORT`, or `FRONTEND_PORT` in `.env` and use the matching API URL.
- **CORS error:** set `CORS_ORIGINS` to the exact browser origin, including scheme and port.

