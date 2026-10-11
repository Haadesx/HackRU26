# Backend Plan

Backend and database for the medication tracking app described in `system.md`, with the schema in `db.md`. This file is the build guide. `db.md` is the source of truth for tables, fields, and constraints.

---

## 1. Decisions

| Topic | Decision |
|---|---|
| Clients | React web app + native iOS app |
| Backend | Flask, REST, JSON, versioned under `/api/v1` |
| Database | TigerData (Postgres + TimescaleDB) |
| Auth | In Flask: JWT bearer tokens (access + refresh) |
| Scan payload | `user_id`, `event_id` (UUID), `drug_name`, `strength`, `quantity`, `timestamp` (UTC) |
| Dose confirmation | Tap to confirm. A scan alone never marks a dose taken. Missed doses can still be confirmed (as late) until `confirm_deadline` |
| On-time windows | Default presets for breakfast, lunch, dinner, bedtime, generic; user-editable |
| Caregivers | View-only. Receive alerts for missed doses, late confirmations of missed doses, and dose mismatches |
| Dose mismatch | Flagged on the dose and sent as a notification to the patient and caregivers |
| Notifications | Push (web only), SMS, in-app, all through one dispatcher. No iOS push: no paid Apple Developer account |
| Prescription details | Label scan creates a draft; instructions and other details are filled in while finalizing the prescription |
| Drug verification | OpenFDA, on prescription entry |
| Low-stock thresholds | Front end. Backend only exposes inventory data |

---

## 2. Stack

| Layer | Tool |
|---|---|
| Language | Python 3.12 |
| Web framework | Flask + flask-smorest (blueprints, validation, OpenAPI/Swagger UI) |
| Schemas / validation | marshmallow (via flask-smorest) |
| ORM | SQLAlchemy 2.x |
| Migrations | Alembic (via Flask-Migrate) |
| DB driver | psycopg 3 |
| Auth | flask-jwt-extended, argon2-cffi |
| CORS | flask-cors |
| Fuzzy matching | rapidfuzz |
| HTTP client | requests (OpenFDA) |
| Push | firebase-admin (FCM web push for the React app) |
| SMS | twilio |
| Jobs | APScheduler in a separate worker process |
| Server | gunicorn |
| Local DB | Docker Compose with `timescale/timescaledb` image, or a TigerData dev service |
| Tests | pytest |

Pin exact versions in `requirements.txt` when the project is created.

---

## 3. Project structure

```
backend/
  app/
    __init__.py            # create_app(), register blueprints, error handlers
    config.py              # env-based config
    extensions.py          # db, migrate, jwt, cors, api
    models/                # SQLAlchemy models, one file per domain
    schemas/               # marshmallow request/response schemas
    api/                   # blueprints: auth, patients, caregivers, medications,
                           #   prescriptions, schedules, windows, doses, scans,
                           #   inventory, refills, notifications, adherence
    services/
      permissions.py       # require_patient_access()
      openfda.py           # search + verify, cached on medications
      matching.py          # scan -> prescription item -> dose event
      adherence.py         # classify dose outcomes
      inventory.py         # apply_transaction(), the only way stock changes
      scheduling.py        # generate dose events from schedules
      notifications.py     # create reminder + fan out deliveries
      channels/            # push.py, sms.py, in_app.py
    jobs/
      worker.py            # APScheduler entrypoint (separate process)
  migrations/
  scripts/seed.py          # demo patient, caregiver, prescription, schedules
  tests/
  docker-compose.yml
  requirements.txt
  .env.example
```

Environment variables (`.env.example`): `DATABASE_URL`, `JWT_SECRET_KEY`, `CORS_ORIGINS`, `OPENFDA_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `FIREBASE_CREDENTIALS_JSON`. Never commit `.env`.

---

## 4. Schema

See `db.md` for every table, field, allowed value, and constraint. Key points for the code:

- Hypertables: `vision_observations` (on `observed_at`) and `dose_outcomes` (on `scheduled_at`), plus the `daily_adherence` continuous aggregate. Create these in a raw SQL Alembic migration.
- `dose_events` snapshots window bounds (`on_time_start`, `on_time_end`, `missed_after`, `confirm_deadline`) at generation, so window edits never rewrite history.
- `dose_outcomes` is upserted on `(dose_event_id, scheduled_at)`, so a late confirmation replaces the earlier `missed` row.
- `push_tokens.platform` is `web` only for now.
- Caregiver `permissions` keys are `view` and `receive_alerts` only.

---

## 5. Core flows

### 5.1 Registration and auth
1. `POST /auth/register` creates the user, hashes the password with argon2, and seeds `dose_windows` for patients.
2. `POST /auth/login` returns access token (15 min) + refresh token (7 days).
3. `POST /auth/refresh` returns a new access token.
4. Every protected route reads the user from the JWT. If a request body includes `user_id` (e.g. scans), it must match the JWT identity. Otherwise, return 403.

### 5.2 Caregiver linking
1. Patient creates an invite: `POST /patients/{id}/caregivers/invite` with caregiver email, returns a short code.
2. Caregiver accepts: `POST /caregivers/accept` with code, link becomes `active`.
3. `services/permissions.require_patient_access(patient_id, write=False)` is called by every patient-scoped route:
   - Patients have full read/write access to themselves.
   - Caregivers with an `active` link and `view` permission get read access.
   - Any write (`write=True`) by anyone other than the patient returns 403. Caregivers are view-only.
4. Patients can revoke a caregiver or toggle `receive_alerts` via `PATCH /caregiver-links/{id}`.

### 5.3 Prescription intake (draft → active)
1. Front end sends extracted label data: `POST /patients/{id}/prescriptions` with items. Creates a prescription with `status = draft`, next `version`.
2. For each item, the backend finds or creates a `medications` row and runs an OpenFDA lookup (`services/openfda.py`). Store `openfda_id`, `rxcui`, `verified`, `verified_at`. Response includes candidate matches for the UI to show.
3. User finalizes the draft: fills in and corrects instructions, dose quantity, quantity prescribed, refills, and schedules via `PATCH /prescriptions/{id}` and `PUT /prescription-items/{id}/schedule`. The label scan only needs to supply what OCR can read; everything else is captured here.
4. `POST /prescriptions/{id}/activate`:
   - Validates every item has a schedule with ≥ 1 time and a window.
   - Returns warnings for unverified medications (does not block).
   - Marks the previous active version `superseded`, deactivates its schedules and cancels its future pending dose events.
   - Creates `medication_inventory` rows if missing (quantity unknown until set).
   - Runs dose event generation for this patient immediately.

OpenFDA notes: query the drug NDC/label endpoints by generic or brand name; cache results on the `medications` row; send the API key; treat timeouts as "unverified", never as a hard failure.

### 5.4 Dose event generation
- `services/scheduling.generate(patient_id, horizon=48h)`.
- For each active schedule time, compute each local occurrence in the patient's timezone between now and the horizon, convert to UTC, and snapshot window bounds:
  - `on_time_start = scheduled_at - on_time_before_min`
  - `on_time_end = scheduled_at + on_time_after_min`
  - `missed_after = scheduled_at + missed_after_min`
  - `confirm_deadline = min(next scheduled_at for the same schedule, scheduled_at + 24h)`
- Insert with `ON CONFLICT (schedule_id, scheduled_at) DO NOTHING`.
- Use `zoneinfo` for timezone math so DST is handled.
- Respect `start_date` / `end_date`.

### 5.5 Scan → match → confirm

**Step 1: scan.** `POST /scans`

```json
{
  "event_id": "uuid",
  "user_id": "uuid",
  "drug_name": "Metformin",
  "strength": "500 mg",
  "quantity": 1,
  "timestamp": "2026-10-10T16:32:00Z"
}
```

1. Auth check (5.1 step 4).
2. Idempotency: if `event_id` exists, return the stored result unchanged.
3. Insert `vision_observations` row.
4. Match (`services/matching.py`):
   - Normalize name (lowercase, strip punctuation) and strength (parse number + unit, e.g. `500mg` = `500 mg`).
   - Compare to the patient's active prescription items with rapidfuzz. Score ≥ 85 and strength equal = match.
   - Multiple items match → `ambiguous`, return candidates.
   - None → `no_match`.
5. Find the `pending` or `missed` dose event for the matched item where `on_time_start ≤ timestamp ≤ confirm_deadline`, closest to `scheduled_at`. None found → `not_due`, return the next upcoming dose.
6. Set `timing`: `on_time` (≤ `on_time_end`), `late` (≤ `missed_after`), or `after_missed` (dose already marked missed, still before `confirm_deadline`).
7. Compare `quantity` to the item's `dose_quantity`; set `quantity_check` to `ok` or `mismatch` so the UI can warn before the user confirms.
8. Store `match_status`, `medication_id`, `dose_event_id` on the observation. Dose status does not change.

Response:

```json
{
  "match_status": "matched",
  "observation_event_id": "uuid",
  "medication": { "id": "...", "name": "Metformin", "strength": "500 mg" },
  "dose_event": { "id": "...", "scheduled_at": "...", "expected_quantity": 1 },
  "timing": "on_time",
  "quantity_check": "ok",
  "candidates": []
}
```

**Step 2: tap to confirm.** `POST /doses/{id}/confirm`

```json
{ "observation_event_id": "uuid", "quantity_taken": 1 }
```

Patient only (`write=True`). In one DB transaction:
1. Lock the dose event. It must be `pending`, or `missed` with `now() ≤ confirm_deadline`. Otherwise, return 409.
2. `taken_at` = scan timestamp if `observation_event_id` is given, otherwise now. `confirmation_method` = `scan` or `manual`.
3. Classify (`services/adherence.py`):
   - `taken_at ≤ on_time_end` → `taken_on_time`
   - otherwise → `taken_late`
   - If the dose was `missed`, also set `confirmed_after_missed = true`.
4. Set `dose_mismatch` if `quantity_taken ≠ dose_quantity`.
5. `inventory.apply_transaction(patient, medication, delta=-quantity_taken, reason="dose", dose_event_id)`, only if inventory is initialized.
6. Upsert the `dose_outcomes` row (replaces a `missed` row if there was one).
7. Cancel any pending `dose_due` / `dose_followup` reminders for this dose.
8. Notifications, created after commit:
   - `dose_mismatch` → `dose_mismatch_alert` to the patient and to caregivers with `receive_alerts`, e.g. "Metformin 500 mg: 2 tablets taken, 1 prescribed."
   - `confirmed_after_missed` → `missed_dose_resolved` to caregivers who got the `missed_dose_alert`.

Manual confirm (no scan) uses the same endpoint without `observation_event_id`, so users can still log a dose if scanning fails.

**Skip.** `POST /doses/{id}/skip`, patient only. Dose must be `pending`. Sets status to `skipped` and upserts `dose_outcomes`. No inventory change, no caregiver alert.

### 5.6 Missed doses and caregiver alerts
Worker job, every minute:
1. Select `pending` dose events where `missed_after < now()` with `FOR UPDATE SKIP LOCKED`.
2. Set status to `missed`; write `dose_outcomes`.
3. Create a `missed_dose_alert` reminder for each active caregiver with `receive_alerts`. Also create an in-app notice for the patient.
4. Hand to the dispatcher.

### 5.7 Reminders
- `dose_due` to the patient at `scheduled_at`.
- `dose_followup` to the patient at `on_time_end` if still pending.
- `missed_dose_alert` to caregivers (5.6).
- `missed_dose_resolved` to caregivers when a missed dose is confirmed late (5.5).
- `dose_mismatch_alert` to the patient and caregivers when the quantity taken differs (5.5).
- `refill_update` to patient and caregivers when a refill is scheduled or fulfilled.

Reminders for a dose are created when its dose event is generated; the dispatcher sends them when due.

### 5.8 Notification dispatch
`services/notifications.dispatch(reminder)`:
1. Create one `notification_deliveries` row per channel:
   - `in_app`: always.
   - `push`: if `push_enabled` and the user has tokens, one send per token.
   - `sms`: if `sms_enabled` and `phone` is set.
2. Each channel sends independently. Failures are recorded on the delivery and don't block other channels.
3. Push: firebase-admin sends FCM web push to the React app. Remove tokens FCM reports as invalid. The iOS app gets no push (no paid Apple Developer account); it relies on SMS and on polling `GET /notifications` for in-app alerts. Adding iOS later means enabling `ios` in `push_tokens.platform` and uploading an APNs key to Firebase; no dispatcher changes.
4. SMS: Twilio. Keep messages short and plain, e.g. "Time to take Metformin 500 mg (1 tablet)."

### 5.9 Inventory
- `services/inventory.apply_transaction()` is the only code path that changes `quantity_remaining`. It locks the inventory row, inserts the transaction, updates the quantity, and rejects results below 0 (manual adjustment is required to correct).
- `PUT /patients/{id}/inventory/{medication_id}` initializes or corrects quantity (`reason = manual_adjustment`).
- Inventory responses include `quantity_remaining`, `quantity_unit`, and `estimated_days_remaining` (from active schedules) so the front end can apply its own thresholds.

### 5.10 Refills
1. `POST /patients/{id}/refills` → `requested`.
2. `PATCH /refills/{id}` with `appointment_at`, `pharmacy_or_provider` → `scheduled`; sends `refill_update`.
3. `POST /refills/{id}/fulfill` with `quantity_added` → `fulfilled`, sets `fulfilled_at`, applies an inventory transaction (`reason = refill`), sends `refill_update`.
4. `POST /refills/{id}/cancel` → `cancelled`.

---

## 6. API endpoints

All under `/api/v1`. All except auth require `Authorization: Bearer <token>`. Patient-scoped routes go through `require_patient_access`. Caregivers can call the `GET` routes for linked patients; every other patient-scoped route is patient-only.

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Get tokens |
| POST | `/auth/refresh` | New access token |
| GET | `/me` | Current user + linked patients/caregivers |
| PATCH | `/me` | Update phone, timezone, notification prefs |
| POST | `/me/push-tokens` | Register browser push token (web only) |
| DELETE | `/me/push-tokens/{token}` | Remove token |
| POST | `/patients/{id}/caregivers/invite` | Create invite code |
| POST | `/caregivers/accept` | Accept invite |
| GET | `/patients/{id}/caregivers` | List caregivers |
| PATCH | `/caregiver-links/{id}` | Toggle `receive_alerts` / revoke (patient only) |
| GET | `/medications/search?q=` | Search known meds + OpenFDA |
| POST | `/medications/{id}/verify` | Re-run OpenFDA verification |
| POST | `/patients/{id}/prescriptions` | Create draft from label data |
| GET | `/patients/{id}/prescriptions` | List versions |
| GET | `/prescriptions/{id}` | Detail with items and schedules |
| PATCH | `/prescriptions/{id}` | Edit draft items |
| POST | `/prescriptions/{id}/activate` | Validate and activate |
| PUT | `/prescription-items/{id}/schedule` | Set schedule + times + windows |
| GET | `/patients/{id}/dose-windows` | List windows |
| PUT | `/dose-windows/{id}` | Edit a window |
| POST | `/patients/{id}/dose-windows` | Add a custom window |
| GET | `/patients/{id}/doses?from=&to=` | Dose events in a range (today view) |
| POST | `/scans` | Ingest scan, return match |
| POST | `/doses/{id}/confirm` | Tap to confirm |
| POST | `/doses/{id}/skip` | Skip a dose |
| GET | `/patients/{id}/inventory` | Stock per medication |
| PUT | `/patients/{id}/inventory/{medication_id}` | Set/correct stock |
| GET | `/patients/{id}/inventory/{medication_id}/transactions` | Stock history |
| POST | `/patients/{id}/refills` | Request refill |
| GET | `/patients/{id}/refills` | List refills |
| PATCH | `/refills/{id}` | Set appointment / pharmacy |
| POST | `/refills/{id}/fulfill` | Mark fulfilled |
| POST | `/refills/{id}/cancel` | Cancel |
| GET | `/notifications` | In-app notifications for current user |
| POST | `/notifications/{id}/read` | Mark read |
| GET | `/patients/{id}/adherence?from=&to=&granularity=day` | On-time / late / missed rates |

Conventions:
- Timestamps are ISO 8601 UTC with `Z`. Local times (`target_time`, `local_time`) are `HH:MM`.
- IDs are UUIDs.
- Errors: `{"error": {"code": "string", "message": "string", "details": {}}}`.
- Status codes: 400 validation, 401 no/invalid token, 403 no access, 404 not found, 409 state conflict.
- Swagger UI at `/api/docs` for the front-end team.

---

## 7. Background worker

Separate process: `python -m app.jobs.worker`. Never run the scheduler inside gunicorn workers.

| Job | Interval | Does |
|---|---|---|
| `generate_dose_events` | 15 min | 48h rolling horizon for all active schedules, plus their reminders |
| `dispatch_due_reminders` | 1 min | Send reminders whose time has come |
| `mark_missed_doses` | 1 min | 5.6 |
| `retry_failed_deliveries` | 5 min | Retry failed push/SMS up to 3 times |

All jobs use `FOR UPDATE SKIP LOCKED` or unique constraints so a duplicate run can't double-send.

---

## 8. Build order

Each phase ends with something the front end can use.

1. **Setup.** Repo layout, config, Docker Compose with TimescaleDB, `create_app`, health check `GET /api/v1/health`, Swagger UI.
2. **Schema.** SQLAlchemy models and Alembic migrations for all tables; raw SQL migration for hypertables (`vision_observations`, `dose_outcomes`) and the `daily_adherence` continuous aggregate. Seed script.
3. **Auth + permissions.** Register/login/refresh/me, `require_patient_access`, caregiver invites. Share the API docs with the front end at this point.
4. **Prescriptions + OpenFDA.** Draft, edit, schedule, windows, activate.
5. **Dose events.** Generation service, `GET /doses`.
6. **Scans + confirm + inventory.** Matching, confirm/skip, inventory service and endpoints.
7. **Worker + notifications.** Missed-dose job, dispatcher; in-app first, then SMS, then web push.
8. **Refills.**
9. **Adherence endpoint** from the continuous aggregate.
10. **Deploy.** Web service + worker service on Render/Railway/Fly.io, pointing at TigerData. Run migrations and seed.

Tests to prioritize: adherence classification boundaries (including confirm after miss and `confirm_deadline`), timezone/DST dose generation, scan idempotency, inventory never going negative, caregivers blocked from every write route.

---

## 9. Assumptions to confirm with the team

1. Default window times: breakfast 08:00, lunch 12:30, dinner 19:00, bedtime 21:30.
2. A missed dose can be confirmed until the next dose of the same schedule, capped at 24 hours.
3. Dose mismatch alerts go to both the patient and caregivers.
