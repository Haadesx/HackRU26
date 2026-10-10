# Backend + Database (Urvi)

Single source of truth for the MedCheck backend. Branch `feat/backend-urvi`. Code lives in `backend/`.
Design inputs: `system.md` (product), `plan.md` (build plan), `db.md` (schema, kept in sync with the code).

Status legend: **implemented** = code exists; **tested** = covered by passing pytest; **verified live** = exercised against running gunicorn + worker + TimescaleDB; **blocked** / **proposed** as stated.

---

## A. Component overview

The backend owns patient data and all medication authority: accounts, caregiver links, prescriptions (draft → active, versioned), OpenFDA verification, dose schedules and on-time windows, concrete dose events, scan matching, tap-to-confirm, missed-dose detection, notifications (in-app, SMS, web push), inventory, refills, and adherence analytics. The inference service (`services/api`, port 8300) only reads labels; clients pass its output to this API.

| Layer | Tech |
|---|---|
| Runtime | Python 3.14.0 (code is 3.11+ compatible; plan said 3.12, 3.14 is what is installed) |
| API | Flask 3.1 + flask-smorest (REST, JSON, OpenAPI/Swagger) under `/api/v1` |
| DB | PostgreSQL 17 + TimescaleDB 2.30.2 (local Docker); TigerData in deployment |
| ORM / migrations | SQLAlchemy 2.1, Alembic via Flask-Migrate |
| Auth | JWT bearer (flask-jwt-extended), argon2 password hashing |
| Jobs | APScheduler in a separate worker process |
| Channels | Twilio SMS, Firebase Cloud Messaging web push, in-app inbox |

Current status: phases 1–9 of `plan.md` implemented and tested; phase 10 (deploy) not started.

## B. What is implemented

| Feature | Status | Main files |
|---|---|---|
| App factory, config, JSON provider (UTC `Z`, `HH:MM`), error envelope | tested | `app/__init__.py`, `app/config.py`, `app/json.py`, `app/errors.py` |
| 17 tables + constraints from db.md | tested | `app/models/*.py`, `migrations/versions/0001_initial_schema.py` |
| Hypertables `vision_observations`, `dose_outcomes`; continuous aggregate `daily_adherence` (+ `daily_adherence_rates` view, hourly refresh policy) | migrated + checked in DB | `migrations/versions/0002_timescale.py` |
| Register / login / refresh / me / push tokens | tested | `app/api/auth.py` |
| Default dose windows seeded on patient registration (breakfast, lunch, dinner, bedtime, generic) | tested | `app/models/enums.py`, `services/prescriptions.seed_default_windows` |
| Caregiver invite (6-char code, 7-day expiry) / accept / revoke / toggle alerts; caregivers read-only | tested | `app/api/caregivers.py`, `services/permissions.py` |
| Prescriptions: draft, edit, schedule, activate (validates, supersedes previous, initializes inventory, generates doses), revise (copy to new draft) | tested | `app/api/prescriptions.py`, `services/prescriptions.py` |
| OpenFDA NDC lookup with strength matching; outage = warning, never failure | tested (mocked) + verified live | `services/openfda.py` |
| Dose windows: list, edit (moves schedule times + rebuilds not-yet-due doses), add custom | tested | `app/api/prescriptions.py` |
| Dose generation, 48h rolling horizon, timezone/DST aware, idempotent | tested | `services/scheduling.py` |
| Scan ingest: idempotent on `event_id`, fuzzy name + strength match, due-dose lookup, quantity check | tested + verified live | `app/api/doses.py`, `services/matching.py` |
| Tap to confirm (scan or manual), late classification, confirm after missed, skip | tested | `services/doses.py`, `services/adherence.py` |
| Missed-dose job + caregiver alerts + "resolved" alert on late confirm | tested | `services/doses.mark_missed`, `jobs/tasks.py` |
| Dose mismatch: flagged on dose, alert to patient + caregivers | tested | `services/doses.py` |
| Notification dispatcher: in-app always, web push per token, SMS if phone set; per-channel delivery rows, retries, dead-token cleanup | tested (channels mocked) | `services/notifications.py`, `services/channels/` |
| Inventory: only via `apply_transaction`/`set_quantity`, transaction log, `estimated_days_remaining` | tested | `services/inventory.py`, `app/api/inventory.py` |
| Refills: requested → scheduled → fulfilled / cancelled; stock top-up; notifications | tested | `app/api/inventory.py` |
| Adherence API (local-day/week buckets) | tested + verified live | `app/api/adherence.py` |
| Worker process | verified live (jobs run, no errors) | `app/jobs/worker.py` |
| Seed script (demo patient, caregiver, 2 meds, 7 days of history) | verified live | `scripts/seed.py` |

Placeholders / not real yet: SMS and push have **never been sent to real Twilio/Firebase** (no credentials here); they are covered only by mocked tests. Deployment is not done.

## C. Design decisions

- **Scan never records a dose.** `POST /scans` only links an observation to a due dose; only `POST /doses/{id}/confirm` changes status (matches inference `safety.ingestion_not_inferred`).
- **Window bounds are snapshotted on each dose event** (`on_time_start/end`, `missed_after`, `confirm_deadline`), so history never changes. Editing a window deletes and regenerates only *pending doses not yet scheduled* (`scheduled_at > now`).
- **`confirm_deadline` = next dose of the same schedule, capped at 24h, never before `missed_after`.** A missed dose confirmed before it becomes `taken_late` with `confirmed_after_missed = true`; the `dose_outcomes` row is upserted (replaced), not duplicated.
- **`dose_events` denormalizes `patient_id`, `prescription_item_id`, `medication_id`** (db.md updated). Generation skips a time if the same medication already has an event at that instant (e.g. taken under the superseded version).
- **Superseding** a prescription deletes the old version's pending events whose window is still open (they are regenerated by the new version) and keeps everything already taken/missed/skipped.
- **Drafts may be incomplete.** `dose_quantity`, `dose_unit`, `instructions` are nullable in the DB and required at activation (400 `PRESCRIPTION_INCOMPLETE` with per-item details).
- **Inventory initialization:** on activation, unknown stock is initialized from `quantity_prescribed` (opt out with `initialize_inventory: false`). A fulfilled refill on unknown stock sets stock to `quantity_added`. Unknown is never treated as zero.
- **Insufficient stock does not block a dose confirm.** The dose is recorded; response carries `inventory.warning = "insufficient_recorded_stock"` and no transaction is written. Manual `PUT` corrects it.
- **Adherence API buckets in the patient's timezone** with `time_bucket(..., tz)` over the hypertable. The `daily_adherence` continuous aggregate is UTC-bucketed (Timescale caggs can't vary timezone per row), so it is kept for analytics but not used by the API.
- **Channels:** patient `missed_dose_alert` is in-app only; everything else fans out to all enabled channels. A channel whose credentials are missing is skipped (no delivery row). Invalid push tokens / permanent SMS errors are not retried; transient failures retry up to 3 attempts.
- **iOS push not supported** (no paid Apple Developer account). `push_tokens.platform` only allows `web`; iOS polls `GET /notifications` and gets SMS.
- **Worker is a separate process** so gunicorn workers never double-send; jobs use `FOR UPDATE SKIP LOCKED` and unique indexes.
- **Caregiver invites require an existing caregiver account** (`caregiver_links.caregiver_id` is required by db.md).
- **Frequencies:** `daily`, `every_other_day`, `weekly` (weekly repeats on `start_date`'s weekday). No as-needed (PRN) support.
- **Medication identity:** unique on `(lower(name), strength, dosage_form)`; strengths normalized (`500mg`, `500 MG`, `{"value":500,"unit":"mg"}`, OpenFDA `500 mg/1` → `500 mg`).

## D. Dependencies and environment

Exact pins in `backend/requirements.txt` (installed and verified on Python 3.14.0, macOS):
Flask 3.1.3, flask-smorest 0.47.0, marshmallow 4.3.1, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.1.4, Flask-Migrate 4.1.0, alembic 1.20.0, psycopg[binary] 3.3.6, Flask-JWT-Extended 4.7.4, argon2-cffi 25.1.0, flask-cors 6.0.5, RapidFuzz 3.14.6, requests 2.34.2, APScheduler 3.11.3, gunicorn 26.2.0, twilio 9.11.2, firebase_admin 7.7.0, python-dotenv 1.2.4, pytest 9.1.1.

Runtime: Python ≥ 3.11, Docker (for local DB), image `timescale/timescaledb:latest-pg17` (TimescaleDB 2.30.2 observed). Package manager: `pip` in `backend/.venv` (uv not installed on this machine).

Environment variables (see `backend/.env.example`; never commit `.env`):

| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (`postgresql+psycopg://...`; add `?sslmode=require` for TigerData) |
| `TEST_DATABASE_URL` | pytest DB (default local `medcheck_test`) |
| `JWT_SECRET_KEY` | Required; app refuses to start without it |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | Token lifetimes (15 / 7) |
| `CORS_ORIGINS` | Comma-separated web origins (default `*`) |
| `OPENFDA_ENABLED`, `OPENFDA_API_KEY`, `OPENFDA_TIMEOUT_S` | OpenFDA lookup |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS (all three or SMS is off) |
| `FIREBASE_CREDENTIALS_JSON` | Service-account file path or raw JSON (web push off if blank) |
| `DOSE_HORIZON_HOURS`, `WORKER_*_INTERVAL_S` | Worker tuning |
| `SEED_PASSWORD` | Password for seeded demo accounts |

External services: OpenFDA (`api.fda.gov/drug/ndc.json`), Twilio, Firebase Cloud Messaging.
Conflict notes: the inference component uses FastAPI on port 8300 and Python 3.11 with its own venv; the backend uses port 8000 and its own `backend/.venv`. No shared Python packages are required.

## E. API and data contracts

Base: `http://<host>:8000/api/v1`. Swagger UI: `/api/docs`; OpenAPI JSON: `/api/openapi.json`. All routes except `/health` and `/auth/register|login` need `Authorization: Bearer <access_token>`.

Conventions: timestamps ISO 8601 UTC with `Z` (inputs must include an offset; naive times are rejected); local times `HH:MM`; IDs UUID; quantities are JSON numbers. Errors:
```json
{"error": {"code": "VALIDATION_ERROR", "message": "Request validation failed.", "details": {"json": {"email": ["Not a valid email address."]}}}}
```
400 validation, 401 token, 403 access (caregivers get 403 on every write), 404, 409 state conflict.

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{status, database, timescaledb, time}` |
| POST | `/auth/register` | `{name, email, password(≥8), role: patient|caregiver, timezone?, phone?}` → `{user, access_token, refresh_token}` |
| POST | `/auth/login` | `{email, password}` → same shape |
| POST | `/auth/refresh` | Bearer = refresh token → `{access_token}` |
| GET/PATCH | `/me` | PATCH `{name?, phone? (E.164), timezone?, sms_enabled?, push_enabled?}`; returns `{user, caregivers}` (patient) or `{user, patients}` (caregiver) |
| POST | `/me/push-tokens` | `{token, platform: "web"}` |
| DELETE | `/me/push-tokens/{token}` | 204 |
| POST | `/patients/{id}/caregivers/invite` | `{email}` → link with `invite_code` |
| POST | `/caregivers/accept` | `{code}` (case-insensitive) |
| GET | `/patients/{id}/caregivers` | |
| PATCH | `/caregiver-links/{id}` | `{receive_alerts?, status?: "revoked"}` |
| GET | `/medications/search?q=` | `{known: [...], openfda: {available, candidates}}` |
| POST | `/medications/{id}/verify` | Re-run OpenFDA |
| POST | `/patients/{id}/prescriptions` | Create draft (below) |
| GET | `/patients/{id}/prescriptions` | Version summaries |
| GET | `/patients/{id}/prescriptions/active` | Full active prescription (added beyond plan) |
| GET / PATCH | `/prescriptions/{id}` | PATCH `{items: [{id?, ...fields}], remove_item_ids: [], effective_at?, source_document_uri?}`; draft only |
| POST | `/prescriptions/{id}/activate` | `{initialize_inventory?: true}` → `{prescription, warnings, superseded_prescription_id, dose_events_created, inventory_initialized_for}` |
| POST | `/prescriptions/{id}/revise` | Copy to new draft (added beyond plan) |
| PUT | `/prescription-items/{id}/schedule` | `{frequency?, start_date?, end_date?, times: [{window_kind | dose_window_id, local_time?}]}` |
| GET / POST | `/patients/{id}/dose-windows` | POST adds custom `{name, target_time?, on_time_before_min?, on_time_after_min?, missed_after_min?}` |
| PUT | `/dose-windows/{id}` | Edit `name/target_time/minutes` |
| GET | `/patients/{id}/doses?from=&to=&status=` | Default: patient's local today; max 31 days |
| GET | `/doses/{id}` | (added beyond plan) |
| POST | `/scans` | Below |
| POST | `/doses/{id}/confirm` | `{observation_event_id?, quantity_taken?}` |
| POST | `/doses/{id}/skip` | |
| GET | `/patients/{id}/inventory` | `[{medication, quantity_remaining (null=unknown), quantity_unit, tracked, estimated_days_remaining}]` |
| PUT | `/patients/{id}/inventory/{medication_id}` | `{quantity_remaining, quantity_unit?, note?}` |
| GET | `/patients/{id}/inventory/{medication_id}/transactions` | |
| POST / GET | `/patients/{id}/refills` | POST `{prescription_item_id, appointment_at?, pharmacy_or_provider?}` |
| PATCH | `/refills/{id}` | `{appointment_at?, pharmacy_or_provider?}` |
| POST | `/refills/{id}/fulfill` | `{quantity_added, fulfilled_at?}` |
| POST | `/refills/{id}/cancel` | |
| GET | `/notifications?unread_only=&limit=` | `{unread_count, notifications: [{id, kind, title, body, patient_id, dose_event_id, refill_request_id, created_at, read}]}` |
| POST | `/notifications/{id}/read` | |
| GET | `/patients/{id}/adherence?from=&to=&granularity=day|week&medication_id=` | `{summary, buckets: [{bucket_start, taken_on_time, taken_late, missed, skipped, dose_mismatch, total, on_time_rate, taken_rate}]}`; rates exclude skipped |

**Create draft** (`POST /patients/{id}/prescriptions`); only `name` is required per item. `strength` may be a string or the inference contract's object:
```json
{"items": [{"name": "Metformin", "strength": {"value": 500, "unit": "mg"}, "dosage_form": "tablet",
  "dose_quantity": 1, "dose_unit": "tablet", "route": "oral", "quantity_prescribed": 60,
  "refills_authorized": 2, "instructions": "Take 1 tablet by mouth twice daily with meals."}]}
```
Each returned item has `verification: {status: verified|unverified|unavailable, candidates}`.

**Scan** (`POST /scans`):
```json
{"event_id": "uuid", "user_id": "uuid", "drug_name": "Metformin", "strength": "500 mg",
 "quantity": 1, "timestamp": "2026-10-12T12:05:00Z"}
```
Response:
```json
{"match_status": "matched", "observation_event_id": "uuid", "observed_at": "...Z", "replayed": false,
 "medication": {...}, "prescription_item_id": "uuid", "dose_event": {...dose...},
 "timing": "on_time", "quantity_check": "ok", "scanned_quantity": 1, "expected_quantity": 1,
 "next_dose": null, "candidates": [],
 "safety": {"ingestion_not_inferred": true, "message": "A scan does not record a dose. Tap confirm after taking it."}}
```
`match_status`: `matched | ambiguous (see candidates) | no_match | not_due (see next_dose)`. `timing`: `on_time | late | after_missed`. `quantity_check`: `ok | mismatch | unknown`. `user_id` must equal the token's user (403). Timestamps > 5 min in the future → 400 `TIMESTAMP_IN_FUTURE`. Replaying an `event_id` returns the stored result with `replayed: true`.

**Confirm** response: `{dose: {...status, taken_at, dose_mismatch, confirmed_after_missed...}, inventory: {tracked, quantity_remaining, warning}}`. 409 codes: `DOSE_NOT_CONFIRMABLE`, `CONFIRM_WINDOW_CLOSED`, `DOSE_NOT_DUE`.

**Dose object** fields: `id, patient_id, prescription_item_id, medication{id,name,strength}, expected_quantity, dose_unit, instructions, window_name, scheduled_at, on_time_start, on_time_end, missed_after, confirm_deadline, status, dose_mismatch, confirmed_after_missed, confirmation_method, confirmed_at, taken_at, quantity_taken, observation_event_id`.

Database: 17 tables exactly as `db.md` (plus Alembic's `alembic_version`), hypertables `vision_observations` (7-day chunks) and `dose_outcomes` (30-day chunks), continuous aggregate `daily_adherence`, view `daily_adherence_rates`.

## F. File structure

```
backend/
  wsgi.py                 # gunicorn/flask entrypoint
  app/__init__.py         # create_app()
  app/config.py           # env config
  app/extensions.py       # db, migrate, jwt, cors, smorest Api
  app/json.py, errors.py, serializers.py, schemas/__init__.py
  app/models/             # user, medication, prescription, dose, notification, inventory, enums
  app/api/                # blueprints: health, auth, caregivers, medications, prescriptions, doses, inventory, notifications, adherence
  app/services/           # permissions, normalize, medications, openfda, prescriptions, scheduling, matching, doses, adherence, inventory, notifications, channels/{sms,push}
  app/jobs/tasks.py       # job bodies; app/jobs/worker.py = worker entrypoint
  app/utils/time.py       # utcnow() (freezable in tests), tz helpers
  migrations/             # Alembic; versions/0001 schema, 0002 TimescaleDB
  scripts/seed.py, scripts/init-test-db.sql
  tests/                  # pytest, real TimescaleDB
  docker-compose.yml, requirements.txt, pytest.ini, .env.example
```

## G. Setup and execution

Verified on macOS (2026-10-10):
```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # set JWT_SECRET_KEY
docker compose up -d            # TimescaleDB on localhost:5433 (+ medcheck_test DB)
.venv/bin/flask --app wsgi db upgrade
.venv/bin/python -m scripts.seed
.venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app     # API
.venv/bin/python -m app.jobs.worker                     # worker (separate terminal)
.venv/bin/python -m pytest                              # 61 tests
```
Untested: deploying to TigerData / Render / Railway / Fly.io; real Twilio/FCM sends.

## H. Integration notes

- **Inference → client → backend.** Inference returns `medication.name.value`, `medication.strength {value, unit}`, `medication.form.value`, `instructions.raw_text`. Clients can pass `strength` objects straight through to `/scans` and to prescription items (`dosage_form` = form value). Instructions/dose amounts come from the user while finalizing the draft.
- Clients must generate a UUID `event_id` per scan and send UTC timestamps with `Z`.
- After a scan, show `quantity_check` / `timing`, then call `/doses/{id}/confirm` with `observation_event_id`. If scanning fails, confirm without it (manual).
- iOS: no push; poll `GET /notifications` (e.g. every 30–60 s, or on app foreground).
- Web push: register the FCM token with `POST /me/push-tokens` after login.
- Low-stock thresholds are the front end's job; use `quantity_remaining` + `estimated_days_remaining`. `quantity_remaining: null` means unknown, not zero.
- Caregiver UI: use `GET /me` → `patients[].patient.id`, then the same patient-scoped GET routes. All writes return 403 for caregivers.
- Access tokens expire after 15 minutes; refresh with `POST /auth/refresh` (refresh token as Bearer).
- CORS allows `Authorization` and `Content-Type`; set `CORS_ORIGINS` to the React dev/prod origins.

## I. Testing and verification

`backend/tests/` (76 tests incl. 15 for `/hub` in `test_hub.py`, all passing; `pytest` 9.1.1 against TimescaleDB 2.30.2, last run 2026-10-10):
- `test_auth_permissions.py`: windows seeded, login/refresh, error envelope, caregiver read-only on every write route, revoke, invite rules.
- `test_scheduling.py`: 48h generation, snapshotted windows, confirm_deadline (next dose / 24h cap), idempotency, local-today view, DST (Nov 1 2026), every_other_day, activation validation, window edit vs history, revise/supersede without duplicates.
- `test_scans_doses.py`: match/fuzzy/no_match/not_due/ambiguous, idempotency, user mismatch, future/naive timestamps, confirm from scan, on-time boundary, early confirm 409, mismatch alerts, skip, insufficient stock.
- `test_missed_notifications.py`: missed job + caregiver/patient alerts, inbox + read, confirm after miss → late + resolved alert, deadline 409, reminder cancellation, SMS/push fan-out (mocked), dead token removal, SMS retry.
- `test_inventory_refills_adherence.py`: initialization from prescription, manual correction, unknown stock, refill lifecycle, adherence in local-day buckets.
- `test_normalize_openfda.py`: strength normalization, OpenFDA matching (mocked HTTP), outage → warning, medication dedupe.

Live verification (gunicorn 2 workers + worker process + seeded DB): `/health` ok with TimescaleDB 2.30.2; login; active prescription with **real OpenFDA verification** (Metformin 500 mg rxcui 861004, Lisinopril 10 mg rxcui 314076); dose list; adherence summary over seeded history; inventory estimates; OpenFDA search (10 candidates); Swagger 200; CORS preflight 200; live scan matched; caregiver write → 403; worker jobs ran every 5 s without errors.

Not verified: real SMS/push delivery, load/performance, TigerData cloud.

## J. Change log

- **2026-10-10** — Branch `feat/backend-urvi` created from `origin/feat/inference-medcheck` (remote has no `main`). Initial backend: all phases 1–9 from `plan.md` (files under `backend/`), migrations 0001/0002, seed, worker, 61 tests passing, live smoke test. Dependencies: see D. Schema changes recorded in `db.md`: `dose_events` gains `patient_id`, `prescription_item_id`, `medication_id`, `window_name`; `vision_observations.received_at`; schedule frequencies; one schedule per item; prescription item fields required at activation; patient in-app missed alert; adherence bucketing note. API additions beyond `plan.md`: `GET /patients/{id}/prescriptions/active`, `POST /prescriptions/{id}/revise`, `GET /doses/{id}`. Commit: `0c1a4fdad6bd0709de6dbc1801a0fb7f8f223879`.
- **2026-10-10** — Pushed `feat/backend-urvi` to origin (first push; tracks `origin/feat/backend-urvi`). No code changes.
- **2026-10-10** — Bug fix: the root `.gitignore` rule `models/` (unanchored) silently excluded `backend/app/models/`, so the first push was missing all model files and would not run from a fresh clone. Cherry-picked the orchestrator's fix (`/models/` anchored to repo root, upstream 179c4d6) and committed the models (`4a01a5b`). Verified: fresh `git worktree` checkout of the branch → `pytest` 61 passed.
- **2026-10-10** — Created `feat/integration` from `origin/feat/inference-medcheck` (which already contains the UI via PR #1) and merged `feat/backend-urvi` (no conflicts). Added the `/hub` compatibility layer (section L): `app/hub/` (routes, state, labels, contacts, rx, defaults), `app/models/hub.py`, migration `0003_hub_compat` (7 hub_* tables), `services/prescriptions.deactivate`, `mark_missed(on_missed=...)` hook, CORS for `/hub/*`, new `HUB_*` env vars. Migration env now ignores TimescaleDB's own hypertable indexes during autogenerate (autogenerate had tried to drop them; dev DB indexes recreated; `flask db check` clean). Tests: 75 passed (61 + 14 hub).
- **2026-10-10** — Merged `origin/feat/integration` (orchestrator's inference v1.3 `label_meta` + `tools/hub_adapter`, a file-backed reference adapter on :8500). `/hub` now prefers `label_meta` over its regex fallback (same mapping as the adapter). The adapter and `/hub` serve the same UI contract; `/hub` persists to the real backend (prescriptions, doses, stock). Choosing one for the demo is a team decision. Tests: 76 passed. Live: UI dev server + inference mock + backend hub, scans through real inference HTTP, complete → new medication, Home/History rendered with real data.

## L. Dashboard compatibility layer (`/hub`)

**Why:** the React dashboard (`frontend/`, Sinchana) was built against its own contract (`frontend/docs/api-contract.md`: no login, integer ids, one polled `GET /state`, photo upload scans, `{"detail": ...}` errors). `/hub` implements that contract exactly on top of the core backend, so the UI runs with no code changes. iOS and other clients keep using `/api/v1`.

**Status:** implemented on `feat/integration`; 15 tests (`tests/test_hub.py`) + verified live with the real UI dev server, the inference gateway (mock mode), and the seeded DB (headless-Chrome screenshots of Home and History rendered real data).

**Security:** `/hub` has **no authentication**. Every request acts as `HUB_PATIENT_EMAIL`. It is registered only when `HUB_ENABLED=true` (default false) and must never be exposed publicly. Run it on localhost for the demo.

**Run the dashboard against the real backend:**
```bash
# inference gateway (mock mode needs only fastapi/uvicorn/python-multipart/pydantic)
python3 -m venv .venv-inference && .venv-inference/bin/pip install "fastapi>=0.110" "uvicorn[standard]>=0.29" "python-multipart>=0.0.9" "pydantic>=2.6,<3"
MEDCHECK_API_MODE=mock .venv-inference/bin/python -m uvicorn services.api.main:app --host 127.0.0.1 --port 8300
# backend (in backend/)
HUB_ENABLED=true CORS_ORIGINS=http://localhost:5173 .venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app
.venv/bin/python -m app.jobs.worker      # optional, for missed doses / reminders / texts
# dashboard (in frontend/)
VITE_API_URL=http://localhost:8000/hub npm run dev
```
Requires the seeded patient (`python -m scripts.seed`) or another patient set in `HUB_PATIENT_EMAIL`.

**Endpoint mapping** (all under `/hub`):

| Dashboard call | Backend behavior |
|---|---|
| `GET /health` | `{"ok": true}` after a DB ping |
| `GET /state` | Built from the active prescription, dose_events, inventory, hub_* tables. Also runs supply-alert checks and scan escalation (side effects on a GET; cheap and idempotent) |
| `POST /medications/{id}/doses` `{method, slot?}` | Confirms today's matching core dose via `services/doses.confirm` (manual). Without `slot`, picks the first dose whose window is open. Never logs a dose before its window opens (409 with the opening time) |
| `POST /medications/{id}/remind` `{slot}` | Records it and sends the patient an in-app/SMS reminder |
| `POST /medications/{id}/counts` `{count, confidence?}` | `inventory.set_quantity` (manual_adjustment). `confidence < 0.8` → 422 "count again" (tray counter rule) |
| `POST /medications/{id}/refill` | Fulfilled `refill_requests` row + refill transaction of `quantity_start`; refills_remaining −1; fill_date today; clears low_* alerts |
| `PATCH /medications/{id}` | Label details (prescriber, pharmacy, purpose, quantity_start, refills_remaining) in hub_medications; `instructions` edits the active item text only; clears `confidence` |
| `DELETE /medications/{id}` | New prescription version without it (or deactivates when it was the last). History kept |
| `POST /scans` (photo) / `POST /scans/{id}/photos` | Photo → inference `POST /v1/scan` (hints = tracked meds) → nine fields, merged by highest confidence |
| `POST /scans` `{manual: true}` | Empty manual scan |
| `GET/DELETE /scans/{id}` | Read / discard |
| `POST /scans/{id}/complete` | Validates (422 readable), adds the medication as a new prescription version with schedule (times matching a preset window use it, others use generic), stock = quantity_start, doses generated immediately |
| `GET /adherence?month=YYYY-MM` | Month calendar from dose_events in the patient's timezone; month 0-based in the response |
| `PUT /settings` | Validated and stored in hub_settings |
| `GET /export` | JSON download of the state |
| `DELETE /data` | Deletes the patient's medications, doses, stock, scans, alerts, events. Settings and caregiver contacts stay |
| `POST /events` `{type, message, at?}` | Wearable mistakes (not called by the UI) |

**Label → field mapping** (`app/hub/labels.py`): name, strength, dose_amount from inference fields with their confidence; schedule_times, quantity, refills, pharmacy, phone, prescriber from inference v1.3 `label_meta` with its confidence. Fallback when `label_meta` is absent or a field is empty: schedule converted from frequency wording (confidence capped at 0.7 → "unsure") and regex over the raw OCR text (0.7–0.75 → "unsure"). Nothing is filled unless it appears in the label text. Cutoffs: ≥0.85 filled, ≥0.5 unsure, else missing. Inference `needs_rescan` adds `guidance` (extra field) without changing fields. Inference down → 503 with a readable sentence.

**Scan status flow:** `reading` → (still missing a required field after 2+ photos) `asking_patient` → after `HUB_ASK_PATIENT_MINUTES` (3) `needs_caregiver` → `complete`. There is no wearable integration yet, so no one actually asks the patient; the history says "Still missing … / Sent to you".

**Texts to dashboard contacts** (`settings.caregivers`, `app/hub/contacts.py`): supply alerts (scopes all + refills), missed doses when `alert_missed` (worker hook, scope all), wrong-bottle/double-dose events when `alert_wrong_bottle`. US numbers are converted to E.164. Skipped when Twilio isn't configured. This differs from `/api/v1`, where alerts go to linked caregiver *accounts*; both run.

New env vars: `HUB_ENABLED`, `HUB_PATIENT_EMAIL`, `HUB_INFERENCE_URL`, `HUB_INFERENCE_API_KEY` (matches the gateway's `MEDCHECK_API_KEY`), `HUB_INFERENCE_TIMEOUT_S`, `HUB_ASK_PATIENT_MINUTES`.
New tables (migration `0003_hub_compat`): see db.md §18.

## K. Known issues and outstanding work

- `/hub` is unauthenticated (demo only; see L). Adding a shared token would need a one-line change in `frontend/src/api/client.js` (teammate's file).
- Dashboard text hard-codes the name "Rosa" in a few places ("Each bottle shows how many days of pills Rosa has left", "Remind Rosa"); `patient.name` from the hub is the seeded "Ada". Frontend change, not done.
- For a medication added mid-day, the dashboard computes earlier slots from `schedule_times` and shows them as not taken/missed, while `/hub/adherence` (backend truth) doesn't count doses that were never scheduled. Seen live on Oct 10 (Amoxicillin 08:00). Frontend computes its own missed list for the day panel.
- Wearable dose logging can't pass its own `taken_at` yet (uses now).
- Inference real mode was not run here (its OCR stack needs Python 3.11 + pinned packages; `rapidocr-onnxruntime==1.4.4` has no wheel for Python 3.14). Verified with the gateway in mock mode only.

- Deployment (plan phase 10) not done; TigerData connection untested.
- Twilio and FCM never exercised with real credentials. Twilio trial accounts only text verified numbers.
- No rate limiting on `/auth/login` and no token revocation/logout list. Add before any public deployment.
- No as-needed (PRN) medications; no per-medication custom reminder text.
- Caregivers must register before being invited (no email invites).
- `daily_adherence` continuous aggregate is UTC-bucketed and unused by the API (see C).
- Dose events are generated 48h ahead; if the worker is down for more than ~48h, patients see no upcoming doses until it runs (activation and window edits generate immediately).
- Seed history is synthetic and uses a fixed status pattern.
- Assumptions awaiting team confirmation (from `plan.md` §9): default window times, 24h confirm cap, mismatch alerts to both patient and caregivers.
