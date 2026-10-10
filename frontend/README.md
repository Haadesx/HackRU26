# MedCheck caregiver web app

The caregiver dashboard for MedCheck, a wearable medication assistant for low-vision older adults.
Built for HackRU's Social Good track.

React 18, Vite, Tailwind CSS and React Router. It runs fully on built-in mock data, so the UI
can be developed and demoed before the backend exists.

## Run it

```bash
npm install
npm run dev        # http://localhost:5173
```

On mock data a **demo bar** sits at the bottom of every screen (Skip 1 day, Skip a week,
Reset demo) for fast-forwarding time during the pitch. Mock data lives in memory, so a page
reload resets it.

### Use the real backend

```bash
cp .env.example .env
# VITE_API_URL=http://localhost:8000
npm run dev
```

With `VITE_API_URL` set, every call goes to the FastAPI hub, `GET /state` is polled every
4 seconds so doses logged by the wearable appear live, and the demo bar is hidden.

The webcam on the Scan tab works on `localhost`. Browsers block cameras on plain `http://`
addresses, so serve over HTTPS if you open the app from another device.

## Screens

| Route | Screen |
|---|---|
| `/` | **Home**: status headline, pill-bottle supply shelf (tap a cap for everything about that medication), today's doses, texts sent, mistakes caught |
| `/scan` | **Scan**: webcam capture, multiple photos per bottle, "Found so far", upload and manual-entry fallbacks |
| `/scan/:scanId/verify` | **Verify**: fill in missing or unclear label fields, then **Preview** with Edit and Add |
| `/scan/added/:medId` | **Added** confirmation |
| `/history` | **History**: adherence calendar, day breakdown, downloadable report |
| `/settings` | **Settings**: caregivers, alert thresholds, reminder options, privacy controls |

## Project layout

```
src/
  api/
    client.js        the contract: same functions in mock and real mode
    mock.js          in-memory demo backend with Rosa's data
  state/AppState.jsx global state, polling, run() helper
  lib/
    inventory.js     days left, status, run-out date, pill count
    format.js        dates and times
  components/        Button (capsule), Card, Dialog, StatusBadge, StatTile, Notice,
                     TextField, Toggle, SectionHeader, EmptyState
  layout/            AppShell, TopNav, HubStatus, DemoBar
  pages/
    Home/            HomePage, StatusHeadline, SupplyShelf, PillBottle, TodayDoses,
                     MedicationPanel, NeedsHelpCard, AlertFeed, MistakesCaught
    Scan/            ScanPage, CameraView, SourcePicker, FoundSoFar, ScanSteps,
                     VerifyPage, ScanTimeline, PreviewDialog, AddedPage, fields.js
    History/         HistoryPage, AdherenceCalendar
    Settings/        SettingsPage
```

## Design system

Pastel blue with dark text, so everything stays readable for older eyes. Tokens are in
`tailwind.config.js`; the capsule button is the `.pill` class in `src/index.css`
(`pill-secondary`, `pill-danger`, `pill-lg`).

| Token | Hex | Use |
|---|---|---|
| `sky` → `ice` | `#9CC3EC` → `#D2E7FB` | Primary capsule blend |
| `mist` | `#E8F1FC` | Selected tab, info backgrounds |
| `page` | `#F5F9FD` | Background |
| `line` | `#D8E3F0` | Borders |
| `navy` | `#1F3A68` | Headings, button text |
| `ink` | `#152238` | Body text |
| `ok` | `#22613B` on `#DCF1E3` | On track |
| `low` | `#6E4700` on `#FCEFCC` | Refill soon |
| `urgent` | `#9A1F14` on `#FBDCD6` | Refill now |

Status rules (in `lib/inventory.js`): days left ≤ 3 is urgent, ≤ 7 is refill soon. Thresholds
come from Settings. Status colors always come with words, never color alone.

## Integrating with this UI

| You're building | Read | Your contract |
|---|---|---|
| The FastAPI backend | [`docs/api-contract.md`](docs/api-contract.md) | Endpoints and JSON shapes the UI calls |
| Label reading, pill counting, the wearable | [`docs/inference-contract.md`](docs/inference-contract.md) | What your models return to the backend |
| Anything | [`docs/fixtures/`](docs/fixtures/) | Real example payloads, generated from the mock |

Nobody needs to edit UI code to integrate. The backend matches the contract, the inference
code feeds the backend, and the UI switches over when `VITE_API_URL` is set.

## API contract for the backend (summary)

Every mutating endpoint returns the full state object (same shape as `GET /state`), except
the scan endpoints, which return the scan.

| Method | Path | Body | Used by |
|---|---|---|---|
| GET | `/health` | | Hub status |
| GET | `/state` | | Every screen |
| POST | `/medications/{id}/doses` | `{ method, slot }` | Log a dose |
| POST | `/medications/{id}/remind` | `{ slot }` | Remind Rosa |
| POST | `/medications/{id}/counts` | `{ count }` | Correct pill count |
| POST | `/medications/{id}/refill` | | Mark refill picked up |
| PATCH | `/medications/{id}` | label fields | Edit details |
| DELETE | `/medications/{id}` | | Stop tracking |
| POST | `/scans` | multipart `photo`, or `{ manual: true }` | First photo / manual entry |
| POST | `/scans/{id}/photos` | multipart `photo` | Each extra photo |
| GET | `/scans/{id}` | | Verify screen |
| DELETE | `/scans/{id}` | | Discard |
| POST | `/scans/{id}/complete` | field values | **Add**, called once; returns `{ medication }` |
| GET | `/adherence?month=2026-10` | | History |
| PUT | `/settings` | settings object | Settings |
| GET | `/export` | | Download data (file) |
| DELETE | `/data` | | Delete all data |
| POST | `/demo/advance`, `/demo/reset` | `{ days }` | Demo bar |

Full details, conventions and error format are in [`docs/api-contract.md`](docs/api-contract.md).
Errors should be FastAPI's `{"detail": "..."}` with a sentence the caregiver can read; the UI shows it.
A scan's `status` is `reading`, `asking_patient`, `needs_caregiver` or `complete`, and each
field has `{ value, state }` where state is `filled`, `unsure` or `missing`. No reminders or
alerts start until a scan is complete.

## Accessibility

Atkinson Hyperlegible type, 44px minimum touch targets, visible focus rings, native `<dialog>`
(Esc closes it and focus returns to the cap that opened it), labeled icon buttons, and reduced
motion respected.
