# MedCheck web UI — handoff (Sinchana)

| | |
|---|---|
| Developer | Sinchana |
| Component | React web dashboard (caregiver app) |
| Branch | `feat/frontend-ui` |
| Code location | `frontend/` |
| Latest UI code commit | **Track tab** commit (SHA: b69a166). Previous: `c733e0c` "UI(React+Tailwind+Vite)" |
| This file | `docs/ui-sinchana.md` |
| Status | Ready for integration. New since `c733e0c`: the **Track** tab and dose scanner (needs two small hub endpoints, see I). |

> **For the orchestrator:** `docs/ORCHESTRATOR_HANDOFF.md` on `feat/integration` lists
> "Sinchana's new UI is still not on the remote". That is out of date: the UI on
> `feat/frontend-ui` @ `c733e0c` **is** the new UI (pill-bottle shelf, medication pop-up,
> 4-tab nav, pastel-blue capsule design). `feat/integration` already contains it plus four
> orchestrator commits on top (`1a739c3`, `f5dcd24`, `00f35b9`, `59ca4d8`). Nothing newer is
> waiting to be pushed.

---

## A. Component overview

The caregiver dashboard. Elena (caregiver) uses it to see whether Rosa (low-vision patient)
has enough of each medication, whether today's doses were taken, and to add new bottles by
scanning their labels.

- **Stack:** React 18 + Vite 5 + Tailwind CSS 3 + React Router 6. JavaScript (no TypeScript).
- **Responsibilities:** display state from the hub, collect caregiver actions (log a dose,
  correct counts, refills, settings), run the scan → verify → preview → add flow, capture
  label photos from the webcam.
- **Not responsible for:** label reading, dose verification, notifications, persistence.
  Those live in the backend (`/hub`) and inference gateway. The UI never calls models.
- **Current state:** feature-complete for the demo. Runs on built-in mock data, or against
  the real hub when `VITE_API_URL` is set.

## B. Implemented functionality

| Screen | Route | What works |
|---|---|---|
| Home | `/` | Status headline from the most urgent medication; **supply shelf of pill bottles** (pill level = days left, colored by status, sorted most urgent first); tapping a bottle **cap** opens the medication pop-up; Today's doses (taken / not taken yet with "Remind Rosa" / reminder sent / upcoming); Needs your help card for incomplete scans; Texts sent to you; Mistakes caught; privacy note |
| Medication pop-up | dialog on Home | Stat tiles (pills left, runs out, refills, this week); "No refills left" banner with call-prescriber and copy-details; Log a dose; Correct pill count; Mark refill picked up; Recent doses; From the label (unsure fields flagged); Edit details; Stop tracking (with confirm) |
| Scan | `/scan` | Live webcam (`getUserMedia`), webcam picker when several exist, multi-photo capture with thumbnails, "Found so far" per-field status, upload-a-photo fallback, enter-by-hand, camera-blocked state, source picker (computer camera; Meta glasses shown disabled as post-MVP) |
| Verify | `/scan/:scanId/verify` | Nine fields with filled / unsure / missing states; partial-scan timeline when Rosa couldn't finish by voice; Preview disabled until required fields are present; Discard |
| Preview | dialog on Verify | Read-only summary with "Added by you" / "Corrected by you" tags; **Edit** returns to the form; **Add** calls complete once (button disabled while sending); error keeps the dialog open with "Try again" |
| Added | `/scan/added/:medId` | Confirmation, scan another, back to home |
| Track | `/track` | Today's doses grouped Morning / Afternoon / Evening with a capsule icon per dose; progress bar; states taken, late (with "N hours late"), reminder sent, upcoming, skipped, missed (past days); **Mark as taken**, **Remind Rosa**, **Skip** (inline confirm); earlier days (up to 13 back, read-only); Coming up next; Taken today log; "How each dose is decided" |
| Dose scanner | card on Track | Source picker (computer camera; Meta glasses disabled, post-MVP), webcam with frame, upload fallback. Results: **match** ("That's Vitamin D3… Rosa took it"), **wrong bottle** (warns and logs a Mistakes caught event), **already taken** (double-dose warning), **nothing due**. A scan never records a dose by itself; "Rosa took it" does |
| History | `/history` | Month calendar (all taken / missed / upcoming), day breakdown, evening-miss suggestion, downloadable text report |
| Settings | `/settings` | Caregivers (scope, add), alert thresholds, three alert toggles, reminder options, sticky save bar, pause camera, export data, delete all data (confirm dialog) |
| Shell | all | Top nav: **Home, Scan, Track, History, Settings**; hub status chip; demo bar (mock mode only). Home's Today's doses now links to Track ("Track and scan doses") |

**Mocked / placeholder behavior (mock mode only, `VITE_API_URL` empty):**
- `src/api/mock.js` holds all data in memory; a page reload resets it.
- Webcam photos are not actually read in mock mode: each photo reveals more of a canned
  "Furosemide 20 mg" label. Real reading happens in the hub + inference gateway.
- The seeded pending scan is **Losartan 25 mg** (not Lisinopril as in early mockups).
- Demo bar (Skip 1 day, Skip a week, Reset) calls mock functions; hidden in real mode.
- The History report downloads as `.txt`, not PDF.
- The dose scanner can't really identify bottles in mock mode: a **"Demo: which bottle is in view?"**
  picker (mock mode only) chooses what the photo "shows", so wrong-bottle and double-dose can be demoed.

**Not built:** camera-based pill counting in the web UI (manual "Correct pill count" only);
login/auth screens; dark mode; i18n; push notifications.

## C. Design decisions

- **Medications tab removed.** All per-medication detail lives in a pop-up opened from a
  bottle cap on Home, because a separate list duplicated the shelf. Tabs are Home, Scan,
  History, Settings.
- **Pill-bottle supply shelf** replaces the earlier horizontal runway bars. 24 pills = full
  bottle = 30+ days (`pillCount` in `src/lib/inventory.js`). Pill color follows status, so a
  bottle's pills turn green → yellow → red as it runs low.
- **Capsule buttons** (`.pill` in `src/index.css`): one rounded, softly shaded capsule with a
  faint center ridge, so every button reads as a pill. Variants: primary, `pill-secondary`,
  `pill-danger`, `pill-lg`, disabled.
- **Pastel blue palette with dark text** (tokens in `tailwind.config.js`). Strong color is
  only used for words, never fills, to keep contrast high for older users. Status colors
  (mint / butter / coral fills, dark text) are separate from the brand blues so a warning
  never looks like a button.
- **Atkinson Hyperlegible** typeface (designed for low-vision readers), loaded from Google
  Fonts with a Verdana fallback.
- **One API seam:** every screen calls `src/api/client.js`; mock and real implementations
  share the same function names, so the backend can be swapped without UI changes.
- **Status is computed in the UI** from `pills_left` and `settings.thresholds` (≤ urgent →
  refill now, ≤ first → refill soon). The backend must use the same rule for texts.
- **Track tab added** (after the 4-tab decision): a full day view of doses, separate from History
  (monthly patterns). Doses are confirmed by **scan, then explicit confirm**, never by scan alone,
  matching the backend rule that `/doses/{id}/confirm` is the only call that records a dose.
- **Dose scanner reuses the Scan tab's camera** (`CameraView`, `SourcePicker` now take props), so
  the Meta glasses can become a second source for both later.
- **Native `<dialog>`** for pop-ups: Esc closes, backdrop click closes, focus returns to the
  opener.
- **Assumption that changed:** the UI docs were written expecting a **FastAPI** hub. The
  real backend is **Flask**, serving the same paths under `/hub`. The `{"detail": "..."}`
  error parsing still works if the Flask hub uses that shape (see I).

## D. Dependencies

| | Version (from `package-lock.json`) |
|---|---|
| Node.js | 18+ required (verified with 22.22.2); npm 10.9.7 |
| react, react-dom | 18.3.1 |
| react-router-dom | 6.30.6 |
| vite | 5.4.21 |
| @vitejs/plugin-react | 4.7.0 |
| tailwindcss | 3.4.19 |
| postcss | 8.5.29 |
| autoprefixer | 10.6.1 |

- Package manager: npm. Manifests: `frontend/package.json`, `frontend/package-lock.json`
  (both committed).
- External services: Google Fonts (optional; falls back to Verdana offline).
- Browser APIs: `getUserMedia` (webcam: needs `https://` or `localhost`),
  `navigator.clipboard` (copy details), `structuredClone` (mock only).
- No other runtime dependencies. No CDN scripts.

## E. APIs, data models and interfaces

Full contract: [`frontend/docs/api-contract.md`](../frontend/docs/api-contract.md).
Example payloads: [`frontend/docs/fixtures/`](../frontend/docs/fixtures/) (generated from the mock).
Inference expectations: [`frontend/docs/inference-contract.md`](../frontend/docs/inference-contract.md).

**Configuration (names only):** `VITE_API_URL`, base URL of the hub. Empty → mock mode.
Against the integrated backend: `VITE_API_URL=http://localhost:8000/hub`.

**Endpoints the UI calls** (all relative to `VITE_API_URL`; the Flask `/hub` blueprint on
`feat/integration` serves every one of them):

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/health` | | `{ ok }` *(currently not called; the chip uses `/state` success)* |
| GET | `/state` | | full state; polled every 4 s in real mode |
| POST | `/medications/{id}/doses` | `{ method: "dashboard" \| "scan", slot }` | state (`method: "scan"` is new) |
| POST | `/medications/{id}/remind` | `{ slot }` | state |
| POST | `/medications/{id}/skip` | `{ slot }` | state **(new, Track)** |
| POST | `/doses/scan` | multipart `photo` | dose match `{ status: match \| wrong_bottle \| already_taken \| not_scheduled, ... }` **(new, Track; records nothing)** |
| POST | `/medications/{id}/counts` | `{ count }` | state |
| POST | `/medications/{id}/refill` | | state |
| PATCH | `/medications/{id}` | `instructions, quantity_start, refills_remaining, prescriber, pharmacy_phone` | state |
| DELETE | `/medications/{id}` | | state |
| POST | `/scans` | multipart `photo`, or JSON `{ manual: true }` | scan |
| POST | `/scans/{id}/photos` | multipart `photo` | scan |
| GET | `/scans/{id}` | | scan |
| DELETE | `/scans/{id}` | | state |
| POST | `/scans/{id}/complete` | nine field values as strings | `{ medication }` |
| GET | `/adherence?month=YYYY-MM` | | adherence |
| PUT | `/settings` | settings | state |
| GET | `/export` | | file |
| DELETE | `/data` | | state |
| POST | `/demo/advance`, `/demo/reset` | `{ days }` | state (mock only in this UI) |

**Shared types (JSON, snake_case):** `Medication`, `Dose` (needs `slot` + `date`),
`Reminder`, `Skip` (new: `{ medication_id, slot, at }`, in state as `skips`), `Alert` (`low_7 | low_5 | low_3 | no_refills`), `Event`
(`wrong_bottle | double_dose`), `Scan` (status `reading | asking_patient | needs_caregiver
| complete`; nine fields each `{ value: string, state: filled | unsure | missing }`),
`Adherence` (note: `missedList` is camelCase), `Settings`. Exact shapes in the contract doc.

**Auth:** none in the UI. The hub is expected to be local/trusted; `/api/v1` JWT is not used
by this UI.

**Inputs expected:** the nine label fields per scan (from the inference gateway via the
hub, mapped per `docs/client-integration.md` §3b on `feat/integration`).
**Outputs provided:** caregiver actions only (doses, counts, refills, edits, completed scans,
settings).

**Breaking changes from earlier versions of this UI:** none. Additive only: `skips` in state,
`method: "scan"`, and the two new endpoints. If the hub lacks them, Track still renders; only
Skip and the dose scanner return an error message.

## F. Project structure

```
frontend/
  index.html                 entry HTML (fonts, root)
  vite.config.js             dev server :5173
  tailwind.config.js         design tokens
  .env.example               VITE_API_URL template (real .env is gitignored)
  public/favicon.svg
  docs/                      api-contract.md, inference-contract.md, fixtures/*.json
  src/
    main.jsx                 entry: BrowserRouter + AppStateProvider
    App.jsx                  routes
    index.css                Tailwind layers, .pill capsule button, .field, .card
    api/client.js            the API seam (mock vs real)
    api/mock.js              in-memory demo backend
    state/AppState.jsx       global state, polling, run()
    lib/inventory.js         days left, status, run-out date, pill count
    lib/format.js            dates and times
    components/              Button, Card, Dialog, StatusBadge, StatTile, Notice,
                             TextField, Toggle, SectionHeader, EmptyState
    layout/                  AppShell, TopNav, HubStatus, DemoBar
    pages/Home/              HomePage, StatusHeadline, SupplyShelf, PillBottle,
                             TodayDoses, MedicationPanel, NeedsHelpCard, AlertFeed,
                             MistakesCaught
    pages/Scan/              ScanPage, CameraView, SourcePicker, FoundSoFar, ScanSteps,
                             VerifyPage, ScanTimeline, PreviewDialog, AddedPage, fields.js
    pages/Track/             TrackPage, DoseRow, DoseScanner
    lib/doses.js             each day's doses and their state (shared by Home and Track)
    pages/History/           HistoryPage, AdherenceCalendar
    pages/Settings/          SettingsPage
```

Runtime assets: `public/favicon.svg` only. Generated (not committed): `node_modules/`, `dist/`.

## G. Setup and execution

| Command | Purpose | Verified |
|---|---|---|
| `cd frontend && npm install` | install | ✅ verified (clean install from the published files) |
| `npm run dev` | dev server at http://localhost:5173 (also on LAN via `--host`) | ✅ verified |
| `npm run build` | production build to `dist/` | ✅ verified, no warnings (~234 kB JS, 74 kB gzip) |
| `npm run preview` | serve the build | ✅ verified |
| `VITE_API_URL=http://localhost:8000/hub npm run dev` | run against the Flask hub | ⚠️ not verified by me; orchestrator reports a headless render against `/hub` on `feat/integration` |

No test command exists (no unit test suite in this component).

## H. Testing and verification

- **Build:** `npm run build` clean on the published code.
- **Track tab (headless Chromium, mock mode, 1280×1000), all passing:** page renders with grouped
  doses and progress; scanner **wrong bottle** (Metformin while Vitamin D3 overdue) shows the warning
  and adds a Mistakes caught event on Home; **match → Rosa took it** moves the headline from 3 to 4 of 6
  and logs "Taken 2:30 PM, scanned"; **already taken** shows the double-dose warning; **Skip → Yes, skip**
  marks the dose Skipped; Previous day shows 6 of 6 for Oct 9; Home shows "Track and scan doses".
  No page errors. Build clean (~249 kB JS, 78 kB gzip).
- **Browser (headless Chromium via Playwright, mock mode, 1280×900):**
  - Home renders; bottles, doses, alerts, needs-help card correct.
  - Opening a bottle cap shows the Atorvastatin pop-up with banner, tiles, doses, label.
  - Verify → fill quantity + prescriber → Preview → Add → routes to `/scan/added/:id`;
    the new medication appears on Home.
  - History calendar and day breakdown render; Settings renders.
  - No page errors (only Google Fonts blocked in the sandbox).
- A single-file hosted demo of this exact code (HashRouter) was used for manual review.
- **Not tested:** a real webcam (headless browser has none); real hub data from my side;
  Safari/Firefox; screen readers; phones (layout is responsive but not device-tested);
  very large Dynamic text sizes.

## I. Integration-relevant issues

1. **Base URL:** must be `http://localhost:8000/hub` (Flask blueprint prefix), not `:8000`.
   `frontend/.env.example` and `frontend/docs/api-contract.md` still show `:8000` and FastAPI
   wording. Functionally fine once the variable is set; docs need a one-line update.
2. **Error format:** the UI reads `{"detail": "..."}` (and FastAPI-style `detail: [{msg}]`).
   The integrated client on `feat/integration` also reads `payload.code` and sets
   `error.status`. Flask hub errors should return JSON with `detail`, or users see a generic
   message.
3. **Integrated frontend is ahead of this branch.** `feat/integration` adds, on top of
   `c733e0c`: wide-screen shell (`1a739c3`, `f5dcd24`), medication verification banner
   (`00f35b9`, `ScanVerification.jsx`, `verificationCache.js`), and required dosage-form
   confirmation (`59ca4d8`, `dosageForm.js`). **Keep those.** They don't conflict with
   anything I plan to change. I have not merged them into `feat/frontend-ui`, per team rules.
4. **Who calls inference** (open team decision in `docs/client-integration.md`): this UI
   assumes the **hub calls inference** server-to-server. It never calls `:8300` directly.
5. **Field mapping** from inference v1.3 to the nine UI fields is documented in
   `docs/client-integration.md` §3b and matches `frontend/docs/inference-contract.md`.
6. **`missedList`** in adherence is camelCase while everything else is snake_case. The hub
   must keep that key (or the UI must be changed together with it).
7. **New hub endpoints needed for Track (Urvi / orchestrator):** the Flask `/hub` blueprint on
   `feat/integration` does not have `POST /hub/doses/scan` or `POST /hub/medications/{id}/skip`, and
   `/hub/state` has no `skips`. Shapes and fixtures: `frontend/docs/api-contract.md` ("Dose match",
   "Skip") and `frontend/docs/fixtures/dose-scan-*.json`. `/doses/scan` can wrap the existing
   `/api/v1/scans` matching; it must not record a dose.
8. **Mock vs real time:** real mode uses the hub's `now`; the demo bar is hidden, so
   fast-forward on stage requires the hub's `/demo/advance` and a UI change to show the bar.

## J. Outstanding work

- Hub endpoints for Track: `POST /doses/scan`, `POST /medications/{id}/skip`, `skips` in state (backend).
- Meta glasses as a dose source (later; same `CameraView`/source picker seam).
- Update `frontend/.env.example` and `frontend/docs/api-contract.md` for the Flask `/hub`
  base URL (small doc change; coordinate with the orchestrator since `feat/integration`
  carries its own copy).
- Decide whether the demo bar should appear in real mode (needs hub `/demo/*`).
- Optional: report as PDF; camera pill counting screen; end-to-end test against `/hub`.
- Before the demo: run the UI against the integrated hub once on the presenting laptop
  (camera permission, `VITE_API_URL`, fonts online).

## K. Development change log

| Date (EDT) | Change | Why | Files | Deps | API changes | Tests | Commit |
|---|---|---|---|---|---|---|---|
| 2026-10-10 | Initial UI: Home with pill-bottle shelf and medication pop-up, Scan with webcam, Verify/Preview/Added, History, Settings, capsule design system, mock backend | First full build of the finalized designs | `frontend/**` | React 18, Vite 5, Tailwind 3, React Router 6 | Defines the hub contract (`frontend/docs/api-contract.md`) | Build ✅; headless browser walkthrough ✅ | `c733e0c` |
| 2026-10-10 | FastAPI-style error parsing (`detail`), API contract + inference contract docs, JSON fixtures, README integration section, `.env.example` notes | So backend and inference can integrate without reading UI code | `src/api/client.js`, `docs/**`, `README.md`, `.env.example` | none | none (docs only) | Build ✅ | included in `c733e0c` |
| 2026-10-11 | **Track tab**: TrackPage, DoseRow, DoseScanner; shared `lib/doses.js`; Track in nav; Home links to Track; `CameraView`/`SourcePicker` take props; mock `matchDose`, `skipDose`, `skips`, `logDose(method)`; client `matchDose`, `skipDose`; contract + 3 dose-scan fixtures | Track what was taken vs still due, confirmed by scanning | `src/pages/Track/**`, `src/lib/doses.js`, `src/App.jsx`, `src/layout/TopNav.jsx`, `src/pages/Home/TodayDoses.jsx`, `src/pages/Scan/CameraView.jsx`, `src/pages/Scan/SourcePicker.jsx`, `src/api/*.js`, `docs/**`, `README.md` | none | **New:** `POST /doses/scan`, `POST /medications/{id}/skip`, `skips` in state, dose `method: "scan"` | Build ✅; headless Track walkthrough ✅ | *b69a166* |
| 2026-10-11 | Added this handoff file and `frontend/AGENTS.md` | Team handoff process | `docs/ui-sinchana.md`, `frontend/AGENTS.md` | none | none | n/a (docs) | *31f286e* |
| 2026-10-11 | Pink heart app icon and favicon | Final app icon chosen | `frontend/public/favicon.svg`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `frontend/index.html` | none | none | Checked in browser | f0be90f |
