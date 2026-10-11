# MedCheck API contract

This is the contract between the caregiver web app and the MedCheck hub (FastAPI). If the
backend matches it, the UI works with no code changes: set `VITE_API_URL` and restart.

- The UI calls every endpoint through `src/api/client.js`.
- `src/api/mock.js` implements the same contract in memory. When this document and the mock
  disagree, the mock is what the UI was tested against.
- Example payloads for every shape are in [`docs/fixtures/`](fixtures/). They were generated
  from the mock, so they are exactly what the UI expects.

## Conventions

| Topic | Rule |
|---|---|
| Base URL | `VITE_API_URL`, for example `http://localhost:8000` |
| Format | JSON, `snake_case` keys |
| Times | ISO 8601 strings with a timezone, e.g. `"2026-10-10T18:30:00.000Z"`. The UI shows them in the browser's local time |
| Dates | `"YYYY-MM-DD"` in the patient's local time zone |
| Dose slots | `"HH:MM"`, 24-hour, matching an entry in the medication's `schedule_times` |
| IDs | Integers |
| CORS | Allow the dashboard origin (`http://localhost:5173` in development). With FastAPI: `CORSMiddleware(allow_origins=[...], allow_methods=["*"], allow_headers=["*"])` |
| Errors | Any 4xx or 5xx with `{"detail": "A sentence the caregiver can read."}` (FastAPI's default). The UI shows `detail` to the user, so write it as plain English, not a stack trace |
| Polling | The UI calls `GET /state` every 4 seconds, so keep it fast. A WebSocket can replace polling later |

### Which endpoints return what

- **Medication and settings writes** return the **full state** (same as `GET /state`). The UI
  replaces its copy with whatever comes back, so the screen updates immediately.
- **Scan endpoints** return the **scan** object.
- `POST /scans/{id}/complete` returns `{ "medication": { ... } }`.
- `GET /export` returns a file (any content type; the UI downloads it).

## Endpoints

| Method | Path | Request body | Response | Used by |
|---|---|---|---|---|
| GET | `/health` | | `{ "ok": true }` | Hub status chip |
| GET | `/state` | | State | Every screen |
| POST | `/medications/{id}/doses` | `{ "method": "dashboard", "slot": "08:00" }` (slot optional: use the next untaken slot today) | State | Log a dose |
| POST | `/doses/scan` | multipart field `photo` | Dose match (see below) | Track tab dose scanner. Identifies the bottle; **records nothing** |
| POST | `/medications/{id}/skip` | `{ "slot": "20:00" }` | State | Track tab: skip a dose on purpose |
| POST | `/medications/{id}/remind` | `{ "slot": "08:00" }` | State | "Remind Rosa": the wearable repeats the reminder |
| POST | `/medications/{id}/counts` | `{ "count": 12 }` | State | Correct pill count. Sets `pills_left` |
| POST | `/medications/{id}/refill` | | State | Refill picked up: `pills_left += quantity_start`, `refills_remaining -= 1` (unless null), `fill_date = today`, remove that medication's `low_*` alerts |
| PATCH | `/medications/{id}` | Any of `instructions`, `quantity_start`, `refills_remaining`, `prescriber`, `pharmacy_phone`, `schedule_times` (`["08:00", "20:00"]` or `"08:00, 20:00"`) | State | Edit details. Clear `confidence` for edited fields. New `schedule_times` replace the dose times from now on; doses already taken keep their history. Bad times → 422 `detail` |
| DELETE | `/medications/{id}` | | State | Stop tracking |
| POST | `/scans` | multipart field `photo` (JPEG), **or** JSON `{ "manual": true }` | Scan | First photo of a new bottle, or manual entry with every field missing |
| POST | `/scans/{id}/photos` | multipart field `photo` | Scan | Each extra photo. Merge with earlier readings |
| GET | `/scans/{id}` | | Scan | Verify screen |
| DELETE | `/scans/{id}` | | State | Discard |
| POST | `/scans/{id}/complete` | Field values, all strings (see below) | `{ "medication": Medication }` | **Add** on the Preview dialog. Called once; return 409 if already complete |
| GET | `/adherence?month=2026-10` | | Adherence | History |
| PUT | `/settings` | Settings | State | Settings save, pause camera |
| GET | `/export` | | File | Download data |
| DELETE | `/data` | | State | Delete all data (keep settings and caregivers) |
| POST | `/demo/advance` | `{ "days": 7 }` | State | Demo bar only. Optional |
| POST | `/demo/reset` | | State | Demo bar only. Optional |

## Shapes

### State (`GET /state`) — see [`fixtures/state.json`](fixtures/state.json)

```jsonc
{
  "now": "2026-10-10T18:30:00.000Z",     // the hub's clock; the demo can move it
  "patient": { "name": "Rosa", "caregiver": "Elena" },
  "hub": { "connected": true },
  "medications": [Medication],
  "doses": [Dose],                        // at least the last 14 days; more is fine
  "reminders": [Reminder],                // today's is enough
  "skips": [Skip],                        // today's is enough
  "alerts": [Alert],                      // newest first
  "events": [Event],                      // newest first
  "scans": [Scan],                        // the UI shows those with status "needs_caregiver" on Home
  "settings": Settings
}
```

### Medication — see [`fixtures/medication.json`](fixtures/medication.json)

| Field | Type | Notes |
|---|---|---|
| `id` | int | |
| `name`, `strength` | string | `"Atorvastatin"`, `"20 mg"` |
| `purpose` | string | Shown after the schedule, e.g. `"for cholesterol"`. May be empty |
| `dose_amount` | int | Tablets per dose |
| `doses_per_day` | int | Must equal `schedule_times.length` |
| `schedule_times` | string[] | `["08:00", "20:00"]` |
| `quantity_start` | int | Tablets in a full bottle; used for refills |
| `pills_left` | number | The UI computes days left as `pills_left / (dose_amount × doses_per_day)` |
| `refills_remaining` | int or null | `null` for over-the-counter |
| `otc` | bool, optional | Over the counter: hides prescription actions |
| `fill_date` | `"YYYY-MM-DD"` | |
| `instructions` | string | From the label |
| `prescriber`, `prescriber_phone` | string | The phone powers "Call Dr. Okafor's office" |
| `pharmacy_name`, `pharmacy_phone` | string | |
| `confidence` | object | `{ "<field>": "unsure" }` for label fields that were hard to read. Empty object when all are clear |

Status (on track, refill soon, refill now) is **computed in the UI** from `pills_left` and
`settings.thresholds`. The backend doesn't need to send it, but must use the same rule when
sending texts: days left ≤ `urgent` is urgent, ≤ `first` is refill soon.

### Dose

```json
{ "id": 1, "medication_id": 3, "slot": "20:00", "date": "2026-10-09", "taken_at": "2026-10-10T00:04:00.000Z", "method": "voice" }
```

`slot` and `date` are required: the UI matches doses to scheduled times with them. A slot with
no dose whose time has passed shows as **missed**. `method` is `voice`, `button`, `dashboard`
or `scan` (confirmed after a Track-tab scan).

### Skip

```json
{ "medication_id": 2, "slot": "20:00", "at": "2026-10-10T18:31:00.000Z" }
```

State includes `"skips": [Skip]` (today's is enough). A skipped slot is not counted as missed in
adherence.

### Dose match (`POST /doses/scan`) — see [`fixtures/dose-scan-*.json`](fixtures/)

The hub identifies which medication is in the photo and compares it with what's due now.
**It must not record a dose.** The caregiver then presses "Rosa took it", which calls
`POST /medications/{id}/doses` with `method: "scan"` and the returned `slot`.

| `status` | Extra fields | UI |
|---|---|---|
| `match` | `medication_id, name, strength, slot, late` | "That's Vitamin D3 1000 IU. Due at 8:00 AM" + Rosa took it |
| `wrong_bottle` | `medication_id, name, strength, expected: { medication_id, name, slot }` | "Wrong bottle". The hub should also add a `wrong_bottle` event |
| `already_taken` | `medication_id, name, strength, slot, taken_at` | "Already taken… would be a double dose" |
| `not_scheduled` | `message` | "Nothing due" |

Unreadable photos: return 422 with a readable `detail` ("Couldn't see a label. Hold the bottle
closer."). On `feat/integration`, the existing `/api/v1/scans` matching logic can back this
endpoint.

### Reminder

```json
{ "medication_id": 5, "slot": "08:00", "date": "2026-10-10", "sent_at": "2026-10-10T18:31:00.000Z" }
```

### Alert (a text that was sent to caregivers)

```json
{ "id": 1, "medication_id": 5, "type": "low_5", "message": "Rosa has about 4 days of Vitamin D3 left.", "sent_at": "..." }
```

`type` is one of `low_7`, `low_5`, `low_3`, `no_refills` (the numbers follow the thresholds in
Settings). The backend creates alerts when supply crosses a threshold, once per threshold per
bottle, and sends the SMS.

### Event (something the wearable caught)

```json
{ "id": 1, "type": "wrong_bottle", "message": "Rosa picked up Metformin when Lisinopril was due. MedCheck stopped her before she took it.", "at": "..." }
```

`type` is `wrong_bottle` or `double_dose` (what the wearable posts to `POST /events`), or, set by the hub itself,
`skipped` (someone pressed Skip, from any device) or `missed` (the worker marked the dose missed). `message` is shown
as written. Clients should show an unknown `type` as a generic heads-up rather than hide it.

### Scan — see [`fixtures/scan-after-photo-1.json`](fixtures/scan-after-photo-1.json) and [`fixtures/scan-needs-caregiver.json`](fixtures/scan-needs-caregiver.json)

```jsonc
{
  "id": 501,
  "status": "needs_caregiver",      // reading | asking_patient | needs_caregiver | complete
  "photos": 2,
  "manual": false,                  // true for "Enter the details by hand"
  "created_at": "...",
  "fields": {
    "name":              { "value": "Losartan", "state": "filled" },
    "strength":          { "value": "25 mg",    "state": "filled" },
    "dose_amount":       { "value": "1",        "state": "filled" },
    "schedule_times":    { "value": "08:00",    "state": "filled" },   // comma-separated
    "quantity_start":    { "value": "",         "state": "missing" },
    "refills_remaining": { "value": "",         "state": "missing" },
    "pharmacy_name":     { "value": "CVS Pharmacy", "state": "filled" },
    "pharmacy_phone":    { "value": "(732) 555-0123", "state": "filled" },
    "prescriber":        { "value": "Dr. Pat?l", "state": "unsure" }
  },
  "history": [                       // shown as a timeline when it has more than one step
    { "step": "Scanned", "at": "...", "detail": "Read 7 of 9 details." },
    { "step": "Asked Rosa", "at": "...", "detail": "“How many tablets came in this bottle?”" },
    { "step": "Rosa wasn't sure", "at": "...", "detail": "She said “I don't know.”" },
    { "step": "Sent to you", "at": "...", "detail": "Waiting for you now." }
  ]
}
```

- All nine field keys must always be present. Every `value` is a **string** (empty when missing).
- `state` is `filled`, `unsure` or `missing`. How confidence maps to these is set in
  [`inference-contract.md`](inference-contract.md).
- Required to add a medication: `name`, `strength`, `dose_amount`, `schedule_times`, `quantity_start`.

#### Partial-scan flow (backend owns the status)

1. `reading`: photos are being read.
2. `asking_patient`: required fields are missing, so the wearable asks Rosa by voice.
3. `needs_caregiver`: Rosa couldn't answer, or 3 minutes passed. Text the caregivers. Home shows
   a "Needs your help" card linking to the Verify screen.
4. `complete`: the caregiver pressed Add. **No reminders or supply alerts until this point.**

### Complete a scan

Request ([`fixtures/scan-complete-request.json`](fixtures/scan-complete-request.json)), all strings
as typed in the form:

```json
{ "name": "Losartan", "strength": "25 mg", "dose_amount": "1", "schedule_times": "08:00",
  "quantity_start": "30", "refills_remaining": "2", "pharmacy_name": "CVS Pharmacy",
  "pharmacy_phone": "(732) 555-0123", "prescriber": "Dr. Patel" }
```

Convert to numbers on the backend, split `schedule_times` on commas, set
`pills_left = quantity_start`, mark the scan `complete`, and return `{ "medication": ... }`
([`fixtures/scan-complete-response.json`](fixtures/scan-complete-response.json)). Validation
errors should be a 422 with a readable `detail`, which the Preview dialog shows.

### Adherence — see [`fixtures/adherence.json`](fixtures/adherence.json)

```jsonc
{
  "year": 2026, "month": 9,          // month is 0-based (9 = October), as in JavaScript
  "due": 58, "taken": 54, "missed": 4,
  "days": [
    { "date": "2026-10-03", "due": 6, "missed": 1, "future": false,
      "missedList": [{ "medication_id": 2, "name": "Metformin", "slot": "20:00" }] }
  ]
}
```

One entry per day of the month. Only count slots whose time has passed. Days after today have
`future: true` and `due: 0`. Note `missedList` is camelCase in the current UI.

### Settings — see [`fixtures/settings.json`](fixtures/settings.json)

```jsonc
{
  "thresholds": { "first": 7, "second": 5, "urgent": 3 },   // days left
  "alert_missed": true, "alert_no_refills": true, "alert_wrong_bottle": false,
  "remind_again": "30",              // "30" | "60" | "never" (minutes)
  "voice_language": "English",
  "camera_paused": false,
  "caregivers": [
    { "id": 1, "name": "Elena", "phone": "(732) 555-0187", "scope": "all", "you": true },
    { "id": 2, "name": "Marco", "phone": "(908) 555-0142", "scope": "refills" }
  ]
}
```

`scope` is `all` or `refills`. Only send texts to these numbers.

## Checking your backend against the UI

1. Run the backend on port 8000 with CORS enabled.
2. In the UI: `cp .env.example .env`, set `VITE_API_URL=http://localhost:8000`, `npm run dev`.
3. Walk through: Home loads, open a bottle cap, Log a dose (pill count drops), Scan → Verify →
   Preview → Add, History calendar, save Settings.
4. If something breaks, compare your response with the matching file in `docs/fixtures/`.
