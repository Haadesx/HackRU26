# iOS app handoff — Aparajita

> Single handoff file for the iOS component. Branch: `feat/ios-aparajita`. Code lives in [`ios/`](../ios/).
> Last updated: 2026-10-11 (fourth milestone: parity with the integrated web app and backend on
> `feat/integrate-track-tab`; third was the Track tab and dose scanner from Sinchana's note
> `MedCheck-iOS-Update.md`, a local source file that is not committed). Status vocabulary: **verified** (I ran it and saw the result),
> **unverified** (written but not run/observed), **not built**.

## Current state in one paragraph

A native SwiftUI iPhone/iPad app that mirrors the caregiver web UI: five tabs (Home, Scan, Track, History,
Settings) plus the medication sheet and the Scan → Verify → Preview → Added flow. It builds and runs on a real
iPhone 15 (iOS 18.5) and in the simulator, on built-in demo data by default. The network client speaks the
shared hub contract **and the extras the backend's `/hub` really sends on `feat/integrate-track-tab`**: the
bottle check (`verification`) with "Log this dose now", the dosage form (tablet/capsule, never guessed), editable
dose times, `pills_left: null`, fractional doses, a wrong bottle that is not a tracked medicine
(`medication_id: null`), `warnings`, patient and caregiver names from `state.patient`, and the hub's own 409/422
sentences. It was run against the **real Flask `/hub`** of `feat/integrate-track-tab` @ `e5e9ed5` (local TimescaleDB in
Docker, seeded patient, gunicorn on `0.0.0.0:8000`, inference gateway in mock mode): 0 failures in the live
contract test, and Home, medication sheet and Verify rendered from its data. It has **not** been run on a phone
since these changes, and no real (non-mock) inference or a due-now wrong-bottle scan was exercised. See section
I.0 for what still differs from the web app and why.

---

## A. Component overview

- **What it is:** caregiver companion app for Elena to check on Rosa's medications from an iPhone: supply
  shelf, today's doses, alerts, scan a bottle label, verify and add a medication, dose history, settings.
- **Stack:** Swift 5 language mode on Xcode 27.0 (27A266a, Swift 6.4 compiler), SwiftUI, Observation
  (`@Observable`), `async/await` URLSession, AVFoundation (camera), Vision (live text-sharpness hint),
  PhotosUI (photo picker), ImageIO / CoreText / UniformTypeIdentifiers. **No third-party packages.**
- **Responsibilities:** UI, local state, camera capture and upload, calling the hub. It does **not** read
  labels itself (inference is server-side) and does **not** own schedules, dose history or prescriptions
  (the backend does).
- **State:** UI feature-complete against the design; client conforms to the shared hub contract (verified with fixtures and a live run against the reference adapter); not yet verified against `/hub` or from a phone.

## B. Implemented functionality

| Area | Status | Files |
|---|---|---|
| 5-tab app (Home, Scan, **Track**, History, Settings), forced light mode | verified (simulator); the 4-tab build ran on iPhone 15 | `ContentView.swift`, `MyApp.swift`, `Services/Router.swift` |
| **Track**: day header and day switcher (13 days back, earlier days read-only), progress bar and counts, Morning / Afternoon / Evening groups, dose rows with Remind Rosa, Mark as taken, Skip (inline confirm), low-supply line, Coming up next, Taken today log, How each dose is decided | verified (demo data on iPhone 17e and iPad simulators, self-test); **not yet on a device** | `Screens/Track/TrackView.swift`, `TrackDoseRow.swift` |
| **Dose scanner**: compact card with camera sheet on iPhone, inline camera on iPad, photo-library fallback, results (match, wrong bottle, already taken, nothing due, marked as taken), glasses option disabled, Debug-only "which bottle is in view" picker | verified on the demo hub in the simulator (camera falls back to the sample label); **real camera and a real hub are unverified** | `Screens/Track/DoseScannerCard.swift`, `Screens/Scan/CameraViewfinder.swift`, `ScanSourcePicker.swift` |
| One derivation for every dose list (`DayDoses.build`, port of `frontend/src/lib/doses.js`): taken / skipped / late / reminded / missed / upcoming, used by Home, Track, History and the sheet, on demo and live data alike | verified (self-test, fixtures) | `Models/DayDoses.swift` |
| Design system: tokens, gel-capsule buttons, status badges, pill bottle + supply shelf, Atkinson Hyperlegible | verified (visual) | `Design/*` |
| Home: headline from most urgent medication, needs-help card, shelf, today's doses with a **Track and scan doses** button, alerts, mistakes caught, privacy note, 5 s polling | verified (demo data) | `Screens/Home/*` |
| Medication sheet: stats, refill banner, call/copy, log dose, correct count, refill picked up, recent doses, label fields, edit, stop tracking | verified (demo data) | `Screens/Medication/MedicationSheet.swift` |
| Scan: camera preview with frame, sharpness hint, torch, photos strip, found-so-far, photo-library upload, manual entry, camera-blocked card | simulator verified (sample label, no camera); **real camera capture unverified** | `Screens/Scan/ScanView.swift`, `Services/CameraService.swift` |
| Verify → Preview → Add → Added flow with field states (filled / unsure / missing), edited-field badges, single-shot Add, inline failure | verified (demo data, self-test) | `Screens/Scan/*` |
| History: month calendar, day breakdown, suggestion, PDF report via share sheet | verified (demo data); share sheet unverified on device | `Screens/History/HistoryView.swift` |
| Settings: caregivers, thresholds, alert toggles, reminders, privacy actions, autosave | verified (demo data) | `Screens/Settings/SettingsView.swift` |
| iPad (regular width) layouts, Dynamic Type through AX XXL | verified in simulator | all screens |
| Demo data hub with clock controls (Skip day / week / Reset) | verified | `Services/MockHub.swift`, `MockAPI.swift` |
| Debug-only: demo bar, hub-connection card, launch args, 68-check self-test, fixture and live-hub contract tests, device snapshot | verified | `Services/Debug*.swift` (`#if DEBUG`) |

**Mocked / placeholder:** all data comes from `MockAPI` unless `MEDCHECK_API_URL` is set. The camera
falls back to a generated sample label when no camera exists (Simulator, Mac).

**Not built:** Meta AI glasses source (option shown disabled; `CameraSource` protocol is the seam),
WebSocket updates (polls instead), dark mode, app icon, localization, push notifications (backend
documents that iOS push is not supported without a paid Apple account), voice input/output, XCTest or UI
test targets.

## C. Design decisions

- **Mirror the web design, adapted to iOS.** Source of truth was `MedCheck-iOS-Handoff.md`
  (kept at `ios/docs/MedCheck-iOS-Handoff.md`) plus the wireframe bundle. No Medications tab: a bottle
  opens a sheet (newer design than the PDF).
- **Screens only talk to `AppStore`; `AppStore` only talks to a `MedCheckAPI`.** `MockAPI` and `LiveAPI`
  implement the same protocol, so the UI never knows which one it has. This is why contract conformance
  can be fixed in one file (`LiveAPI.swift`) without touching screens.
- **Demo data by default.** The app must work with no hub in the room.
- **Status is computed on the device** from `pills_left`, `dose_amount × doses_per_day` and the settings
  thresholds (same rule as the web UI and the contract).
- **Light mode only for now** (design tokens are light; dark variants were deferred by the design handoff).
- **Dynamic Type is not capped in content.** Exceptions: pinned top bar stops at the largest
  non-accessibility size; the History calendar becomes a list at accessibility sizes.
- **Minimum iOS 18.0** (template said 27.0, which blocked iOS 18 phones). Code uses `Tab`, `ScrollPosition`
  and `onGeometryChange`, which need iOS 18.
- **Contract translation lives in one place.** `Services/HubContract.swift` holds the wire DTOs and pure
  mapping functions; `LiveAPI` only moves bytes. The hub has no per-medication, per-day or settings reads,
  so, like the web app, the client derives today's slots, "reminder sent", recent doses, the weekly count and
  the History insight from the single `GET /state`.
- **Tolerant decoding.** Ids may be numbers or numeric strings, and one malformed list entry is skipped
  instead of failing the whole state (the reference adapter really does return `"medication_id": "5"`).
- **Supply bottles are drawn at 75% of the handoff size** (`BottleMetrics.scale` in `Design/PillBottleView.swift`)
  so two full bottles plus the edge of a third fit on an iPhone beside the "Days left" column. The text under
  each bottle keeps its size; the on-bottle name is 13 pt (it shrinks only for long names).
  **Measured on a physical iPhone 15 (393 × 852 pt, default text size): two full bottles plus the edge of a
  third.** In the simulator at 390 pt wide, two still fit at Extra Large through the largest regular size
  (at the largest the second bottle's badge touches the card edge); at accessibility text sizes only one
  fits and the row scrolls.
- **Dose rows are derived, not stored.** `HubState` carries the hub's raw `doses`, `reminders` and `skips`; every
  list of doses is `DayDoses.build(day:now:...)`, so the demo hub (`MockHub`, now built on the same records) and
  a real hub are read by exactly the same rules, and Home, Track, History and the sheet cannot disagree.
- **A scan never records a dose.** The scanner only identifies the bottle; "Rosa took it" is the single path to a
  dose, and it calls the same endpoint as "Mark as taken" with `method: "scan"`.
- **The hub's own sentence wins.** When the hub answers with an error its `detail` is shown as written
  ("Lisinopril was already taken at this time today.") and the connection chip stays green, because the hub was
  reachable. Only "no answer" turns the chip red. A bare `{"detail":"Not Found"}` or an HTML 404 on the two new
  routes becomes "This hub can't skip doses yet." / "This hub can't scan doses yet."
- **Skipped is not missed**, in rows, counts and the demo adherence. The demo's "55 of 58" now comes from one
  rule (today's late doses count as due but are not "missed" until the day is over) instead of a hard-coded number.
- **Greeting follows the clock** instead of the web's hard-coded "Good morning".
- **iOS-only APIs are fenced** (`#if os(iOS)`) so the target still compiles for macOS.

## D. Dependencies

| Item | Version / value |
|---|---|
| Xcode | 27.0 (27A266a); iOS SDK 27.0 |
| Swift | compiler 6.4, `SWIFT_VERSION = 5.0` (Swift 5 mode), `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor` |
| Deployment target | iOS 18.0 (`IPHONEOS_DEPLOYMENT_TARGET`) |
| Device family | iPhone and iPad (`TARGETED_DEVICE_FAMILY = 1,2,7`); `SUPPORTED_PLATFORMS` also lists macOS and visionOS (macOS builds; visionOS never built) |
| Package managers / lockfiles | none (no SPM, CocoaPods or Carthage) |
| Apple frameworks | SwiftUI, Observation, Foundation, AVFoundation, Vision, PhotosUI, ImageIO, CoreText, UniformTypeIdentifiers |
| Font | Atkinson Hyperlegible 1.006 Regular + Bold, SIL OFL 1.1 (`Fonts/`, license included) |
| External services | the MedCheck hub (optional); nothing else |
| Compatibility risks | iOS < 18 not supported. Local-network prompt appears on first hub connection. HTTP (not HTTPS) to an IP address works because ATS does not apply to raw IPs; a `.local` or DNS name over HTTP may need an ATS exception. |

## E. APIs, data models and interfaces

### E1. Target contract (what the iOS client must speak)

The shared UI↔hub contract is `frontend/docs/api-contract.md` with fixtures in `frontend/docs/fixtures/`.
It is served by **Urvi's `/hub`** (`HUB_ENABLED=true`, Flask, port 8000, base `http://<host>:8000/hub`) and by
**Apollo's reference `tools/hub_adapter`** (FastAPI, port 8500). Both are unauthenticated demo surfaces and
must not be exposed publicly. `/api/v1` (JWT) is a different model and is **not** used by this app.

### E2. What the iOS client sends (`Services/LiveAPI.swift`) — conforms to the contract

Base URL = `MEDCHECK_API_URL` (or the Debug-only Settings card). No auth header. JSON keys are snake_case,
times ISO 8601. Writes return the full State, which the client keeps for derived reads.

| Method | Path | Body | Used for |
|---|---|---|---|
| GET | `/health` | | hub chip |
| GET | `/state` | | everything (polled every 5 s on Home) |
| POST | `/medications/{id}/doses` | `{"method":"dashboard"}` (no slot: next untaken slot), or `{"method":"dashboard"\|"scan","slot":"08:00"}` | Log a dose; Mark as taken; Rosa took it (`scan`) |
| POST | `/medications/{id}/skip` | `{"slot":"20:00"}` | Skip on purpose (Track). Returns State. **Backend: not there yet** |
| POST | `/doses/scan` | multipart field `photo` (JPEG) | Dose scanner. Identifies the bottle, **records nothing**. Returns a dose match. **Backend: not there yet** |
| POST | `/medications/{id}/remind` | `{"slot":"08:00"}` | Remind Rosa |
| POST | `/medications/{id}/counts` | `{"count":12}` | Correct pill count |
| POST | `/medications/{id}/refill` | | Mark refill picked up |
| PATCH | `/medications/{id}` | `instructions, quantity_start, refills_remaining (null for OTC), prescriber, pharmacy_phone` | Edit details |
| DELETE | `/medications/{id}` | | Stop tracking |
| POST | `/scans` | multipart field **`photo`** (JPEG), or `{"manual":true}` | first photo / manual entry |
| POST | `/scans/{id}/photos` | multipart field `photo` | more photos |
| GET | `/scans/{id}` | | Verify |
| DELETE | `/scans/{id}` | | Discard |
| POST | `/scans/{id}/complete` | the nine fields as strings | Add (once) |
| GET | `/adherence?month=2026-10` | | History |
| PUT | `/settings` | full Settings | autosave, camera pause/resume (`camera_paused`) |
| GET | `/export`, DELETE `/data` | | privacy |
| POST | `/demo/advance` `{"days":n}`, `/demo/reset` | | Debug demo bar |

Errors: `{"detail": "..."}` or `{"detail":[{"msg":...}]}` is shown to the caregiver as written (409/422 on Add).

### E3. Contract conformance status

| Area | Status |
|---|---|
| State shape (`now, patient, hub, medications, doses, reminders, alerts, events, scans, settings`) | conforms, verified against `state.json` and live |
| Derived: today's rows, reminded/late, recent doses, week count, label rows, History day breakdown | conforms to the web's logic, verified (fixtures + live) |
| Scan: nine string fields keyed `name … prescriber`, `photos`, `manual`, `history[]` | conforms, verified against three scan fixtures and live manual scan |
| Complete request/response, 409/422 handling | conforms; hub deviation noted in I |
| Adherence: `year`, 0-based `month`, `due/taken/missed`, `days[].missedList` | conforms, verified (fixture + live) |
| Settings: `thresholds`, `alert_*`, `remind_again "30"|"60"|"never"`, `voice_language`, `camera_paused`, `caregivers[].you` | conforms; round trip verified live |
| Camera pause **and resume** via `PUT /settings` | conforms, verified live |
| Edit details limited to the five PATCH fields | conforms |
| `skips: [{medication_id, slot, at}]` in State | conforms, decodes (empty in the fixture); absent on the reference adapter, which is tolerated |
| `method: "scan"` on a dose, shown as "scanned" | conforms, verified live (the adapter accepts it) |
| Dose match: `match`, `wrong_bottle` (with `expected`), `already_taken` (with `taken_at`, `slot`), `not_scheduled` (`message`) | conforms, verified against the three `dose-scan-*.json` fixtures; an unknown status is a bad response |
| `POST /doses/scan` 422 "Couldn't see a label" | the hub's sentence is shown in the card as written (not testable until the backend has the route) |
| "Ask Rosa to scan again" | **not in the contract or the web UI**: shown in demo mode only, hidden against a real hub (`MedCheckAPI.supportsRescan`) |
| Dosage-form-aware labels ("Capsules in bottle" in `frontend/src/lib/dosageForm.js`) | **not mirrored**; iOS always says "tablets" |
| Patient/caregiver names from `state.patient` | **not used**; "Rosa" and "Elena" are fixed design copy (the web hard-codes "Rosa" in places too) |

### E4. Inputs from / outputs to other components

- **From the hub:** everything above. **To the hub:** JPEG label photos (multipart), caregiver edits.
- **Inference gateway (`:8300`) is never called directly by this app**; label reading happens behind the hub
  (consistent with the "hub-proxied inference" recommendation in `docs/client-integration.md`).
- **Authentication:** none (matches `/hub` and `hub_adapter`). Any LAN exposure needs the team's decision.
- **Configuration (names only):** env var `MEDCHECK_API_URL`; Debug UserDefaults keys
  `medcheck.hubBaseURL`, `medcheck.useDemoData`. No secrets are stored in the app.
- **Permissions (Info.plist build settings):** `NSCameraUsageDescription`,
  `NSPhotoLibraryUsageDescription`, `NSLocalNetworkUsageDescription`.

## F. Project structure

```
ios/
  README.md                         short component readme (points here)
  docs/MedCheck-iOS-Handoff.md      design handoff the UI was built from
  frontendmobileapp.xcodeproj/      Xcode project (file-system-synchronized group)
  frontendmobileapp/
    MyApp.swift                     @main entry, injects AppStore + Router
    ContentView.swift               TabView
    Design/                         Theme, Typography, CapsuleButtonStyle, Components, PillBottleView, Platform
    Models/                         Models (wire types), Formatting, ScanFieldKeys
    Services/                       MedCheckAPI, LiveAPI, MockAPI, MockHub, AppStore, Router, AppConfig,
                                    CameraService, DebugLaunch + DebugSelfTest (DEBUG only)
    Screens/                        Home, Medication, Scan, History, Settings
    Fonts/                          Atkinson Hyperlegible + OFL.txt
    Assets.xcassets/                AccentColor only (no app icon yet)
```

Entry point `MyApp`. Fonts are registered at runtime (`MCFont.registerFonts`), no `UIAppFonts` entry.
32 Swift files, about 6.7k lines.

## G. Setup and execution

Run from the `ios/` directory. "Verified" means I ran it and it succeeded.

| Purpose | Command | Status |
|---|---|---|
| Build for simulator | `xcodebuild -project frontendmobileapp.xcodeproj -scheme frontendmobileapp -destination 'platform=iOS Simulator,name=iPhone 17' build` | verified, 0 errors, 0 warnings |
| Build for macOS | `… -destination 'platform=macOS' build` | verified |
| Compile for device, unsigned | `… -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build` | verified |
| Signed build + install on iPhone | set your own Team in Signing & Capabilities, then Run (or `xcodebuild … -destination 'id=<udid>' -allowProvisioningUpdates`, `xcrun devicectl device install app`) | verified on an iPhone 15, iOS 18.5 |
| Demo mode | nothing to do | verified |
| Point at a hub | Settings, Hub connection (any build): demo data off, type `<mac-ip>:8000` and Apply (MedCheck finds `/hub`), or set `MEDCHECK_API_URL=http://<host>:8000/hub` in the scheme (`:8500` for `tools/hub_adapter`). The backend must listen on `0.0.0.0`, not `127.0.0.1` | verified against the real `/hub` (above), `tools/hub_adapter` and a wire-shape stub, from the simulator; a phone **unverified** |
| Screenshot a physical device (Debug) | `xcrun devicectl device process launch --device <udid> --terminate-existing <bundle id> -- -medcheck.snapshot 1 -medcheck.scrollY 880`, wait about 10 s with the phone **unlocked**, then `xcrun devicectl device copy from --device <udid> --domain-type appDataContainer --domain-identifier <bundle id> --source Documents/medcheck-snapshot.png --destination out.png` | verified on iPhone 15 |
| In-app demo self-test (106 checks) | `xcrun simctl launch --console-pty booted <bundle id> -medcheck.selfTest 1` | verified, 106/106 against `MockAPI` |
| Contract fixtures (32 checks) | `… launch --console-pty booted <bundle id> -medcheck.fixtures <repo>/frontend/docs/fixtures` | verified |
| Live hub (34 checks) | start the adapter (below), then `SIMCTL_CHILD_MEDCHECK_API_URL=http://127.0.0.1:8500 xcrun simctl launch --console-pty booted <bundle id> -medcheck.liveTest 1` | verified |
| Reference hub for the live test | from a checkout with `tools/hub_adapter` (`feat/integration`): `uv venv --python 3.11 .venv-hub && uv pip install --python .venv-hub/bin/python fastapi "uvicorn[standard]" httpx python-multipart`, then `HUB_MODE=demo HUB_STATE_FILE=/tmp/hub/state.json HUB_SCANS_DIR=/tmp/hub/scans .venv-hub/bin/python -m uvicorn tools.hub_adapter.app:app --host 127.0.0.1 --port 8500` | verified |

Environment: macOS with Xcode 27. Device: Developer Mode on, device trusted, a development Team selected
(the Team ID and bundle ID committed in `project.pbxproj` are Aparajita's personal ones, not secrets, but
change them). Debug launch arguments are listed in `ios/README.md`.

## H. Testing and verification

| Item | Result |
|---|---|
| Simulator build (iPhone 17, iOS 27 runtime), macOS build, generic iOS device compile (min 18.0), **Release configuration** | all pass, 0 warnings (2026-10-11) |
| Signed build installed and launched on iPhone 15 (`iPhone15,4`, iOS 18.5) | passes (first milestone build); Aparajita reported it "looks good". The contract-conforming build has **not** been reinstalled on the phone yet |
| In-app demo self-test (`-medcheck.selfTest 1`) | 106/106 against `MockAPI`: the earlier 68 (incl. Track) plus parity checks: strict 24-hour times, dosage-form reading and wording, form rejection vs count errors, half doses, uncounted stock, settings the hub would refuse, phone rule, hub address normalisation, editing dose times, and decoding of the real `/hub` shapes below |
| Real-`/hub` wire shapes (`DebugContractTest.runRealHubShapes`, runs inside the self-test) | all pass: `pills_left: null`, `dose_amount: 0.5`, `dosage_form`/`dose_unit`, settings without `camera_paused`, scan extras (`guidance`, `dosage_form`, `verification` incl. unknown status and `can_log: false` failing closed), `wrong_bottle` with `medication_id: null` and `expected.medication_id: null`, `already_taken` with microsecond timestamp, `not_scheduled` extras, adherence `missedList` with a null id, `complete` with `warnings`. Shapes were read from `backend/app/hub/{state,verify,dose_scan,routes}.py` at `e5e9ed5`, **not** captured from a running backend |
| Live client against a stub of `/hub` (`-medcheck.liveTest 1`) | all requests accepted and decoded; the 2 "failures" are the stub not keeping state. Stub is test scaffolding, not the backend |
| **Live client against the real Flask `/hub`** (`feat/integrate-track-tab` @ `e5e9ed5`, seeded `demo.patient@example.com`) | 0 failures, 0 client-side surprises. Verified: `locateHub` finds `/hub` from host:port; state decodes (`patient` Ada/Cara); the hub's 409 `NOT_DUE`/`NOTHING_DUE` sentences surface; counts, refill, skip, PATCH, manual scan, GET scan, **complete with the caregiver's `dosage_form`** and a second complete rejected, photo upload through the inference gateway (mock), adherence, settings, camera pause, export. Confirmed with curl on the same hub: complete without a form returns the `FORM_UNCONFIRMED` sentence; **`"8:00 AM"` is refused (`“8:00 AM” isn't a time…`), so the app's 24-hour conversion is required**; PATCH `["9am"]` 422; `schedule_times` PATCH works; thresholds 422. Real scan responses carry `dosage_form`, `verification` and `+00:00` timestamps; the app renders them (Verify: "We couldn't confirm this bottle") |
| Contract fixtures (`-medcheck.fixtures <frontend/docs/fixtures>`) | 38/38 using `feat/frontend-ui` @ `7427487`: `state` (with `skips`), `settings`, three scans, `scan-complete-*`, `adherence` and the three `dose-scan-*` fixtures decode and map; settings re-encode to contract keys |
| Live hub (`-medcheck.liveTest 1`, `MEDCHECK_API_URL`) against `tools/hub_adapter` in demo mode, from the simulator | 35 pass, 0 failures, 4 hub-side notes (see I). Covers health, state, dose (also `method: "scan"` with a slot), remind, count, refill, PATCH, manual scan, GET scan, complete, adherence, settings PUT, camera pause/resume, export, demo advance/reset, photo field name. `/skip` and `/doses/scan` answered 404, reported as notes |
| Visual QA on live data | Home, medication sheet, Verify, Preview, History, Settings rendered from the adapter |
| Visual QA of Track | iPhone 17e and iPad Pro 11" simulators: today, an earlier day (Wed, Oct 7: 2 missed, read-only), the late row's three actions, low-supply line, and all four scanner results plus "Marked as taken" |
| Merge check | `feat/ios-aparajita` merges with **0 conflicts** into `feat/inference-medcheck`, `feat/integration`, `feat/frontend-ui`, `feat/backend-urvi` and `main` (scratch worktrees, nothing pushed). My change touches only `ios/` and this file (inside `ios/`: the project file gains `INFOPLIST_FILE` and a new `ios/Config/MedCheck-Info.plist` with `NSAllowsLocalNetworking`) |
| SonarCloud | 1 bug + 39 smells fixed in `d5e922e`; no new analysis seen yet |

**Not tested:** Track and the dose scanner **on a physical iPhone**; real camera capture for a dose scan; the
`/skip` and `/doses/scan` routes (no hub has them); Urvi's `/hub` (Flask, port 8000) and any real inference scan (the adapter returned 502 for a
photo upload because inference was not running; the `photo` field name was accepted); real camera capture
and sharpness hint on a device; share sheets, tel: and Local Network prompt on a device; VoiceOver; iPad
hardware; no XCTest or UI test target exists (checks are in-app, Debug only).

**Known failures:** none in what is tested.

## I. Integration-relevant issues

0. **iOS vs the integrated web app (`feat/integrate-track-tab` @ `e5e9ed5`).** What matches, what was changed to
   match, and what is still different:

   | Area | Web + `/hub` | iOS now |
   |---|---|---|
   | Buttons → endpoints | `doses`, `skip`, `doses/scan`, `remind`, `counts`, `refill`, `PATCH`, `DELETE`, scans, `complete`, `adherence`, `settings`, `export`, `data` | same paths and bodies; Log a dose / Mark as taken / Rosa took it (`method: "scan"`) / Skip / Remind Rosa / count / refill / edit / stop / add / settings / export / delete data |
   | "Log this dose now" on a scan check | `verification.due_now` + `can_log`, one tap, normal dose endpoint | added: `VerificationCard`, six outcomes, never auto-logs, fails closed on unknown status |
   | Dosage form | chooser when the label didn't say; `dosage_form` sent; 422 `FORM_UNCONFIRMED` shown at the chooser; "Tablets/Capsules/Units" labels | added, incl. form-aware Found so far, Verify, Preview, Added, medication sheet |
   | Edit details | adds `schedule_times` (24-hour, only if changed) | added, same validation sentence |
   | Dose scanner | wrong bottle may have `medication_id: null` | fixed: this used to be read as an unreadable answer; hub's reason sentence now shown for unknown medicine / wrong strength |
   | Stock never counted | `pills_left: null` (web shows 0 / "out of") | not dropped; shown as "Not counted"; Mark as taken stays on. **Deliberately differs from web** |
   | Fractional doses | number | `Double`; was an Int that would have dropped the medication |
   | Names | `state.patient` in greeting and Settings; "Rosa/Elena" hard-coded elsewhere | greeting and Settings use `state.patient`; the rest stays hard-coded exactly like web |
   | Alerts / events | "Texts sent to you" (5 newest, empty text), "Mistakes caught" | same; no OS push in either client |
   | Settings | explicit Save; hub 422 on thresholds / phone | autosave, but values the hub would refuse are held back with the hub's sentence; phone rule copied from `to_e164` |
   | Hub address | `VITE_API_URL=…/hub` | Settings card in all builds; host:port alone is enough (`/hub` is found); `NSAllowsLocalNetworking` |
   | Live updates | polls `/state` every 4 s | polls every 5 s while Home is visible; Track and others refresh after each action |

   **Still different or missing (not fixable in the iOS app alone):**
   - The hub must be reachable from the phone: `run_ui_demo.sh` binds `127.0.0.1:8000`; it needs `0.0.0.0` (or
     Tailscale). `/hub` is unauthenticated, so LAN/Tailscale only.
   - **No iOS push.** The hub's reminders and supply/mistake texts go to in-app inbox/SMS (Twilio, never tested
     with real credentials) and web push; `docs/backend-urvi.md` says iOS push is not supported (no paid Apple
     Developer account). The iOS app shows the same in-app lists as the web, nothing at the OS level.
   - Not exercised: real (non-mock) inference, and a `wrong_bottle` scan with a dose due *now* (the seeded doses
     were all done or closed; the mock inference always reads Ibuprofen/Amoxicillin). Its `medication_id: null`
     shape comes from reading `dose_scan.py` and is covered by decode tests only.
   - Time zone: the app derives "today" in the device's zone, like the browser. If the patient's zone differs from
     the phone's, slots can read shifted. The state has no zone field.
   - "Rosa" is hard-coded in many strings on both clients (backend doc, "known limitations").
   - "Ask Rosa to scan again" still has no endpoint.

1. **`/hub` is unauthenticated** and documented for localhost. A phone needs it on the LAN or Tailscale. Either
   bind it to a LAN address for the demo or add a token (needs Urvi's and Sinchana's agreement).
2. **Observed hub behaviors (reference adapter, demo mode)** that differ from `api-contract.md`. The client
   tolerates all of them; the owners may want to fix them:
   - `POST /medications/{id}/doses` returns the new dose with `"medication_id": "5"` (a string, contract says
     integer). In JS the web's strict `===` would also fail to match it.
   - A logged dose does not reduce `pills_left` (the web mock does; the contract's walkthrough says "pill
     count drops").
   - `POST /scans/{id}/complete` called twice returns 200 (contract: 409). The real `/hub` returns 409.
   - New doses carry the real wall-clock `taken_at` while `now` is the fixed fixture time, so the dose is not
     "today" and the slot stays late.
   - `adherence.json` fixture has 12 days; the doc says one entry per day of the month.
3. **Time zones.** Dose `slot` ("08:00") is a wall-clock time, while fixture ISO timestamps are UTC. In a
   non-UTC time zone the derived "Taken 4:14" can look shifted (same on web). The backend should send times
   whose local reading matches the slot, or include the patient's time zone.
4. **No `rescan` endpoint** for "Ask Rosa to scan again" (hidden against a real hub).
4a. **(Superseded for `feat/integrate-track-tab`, which has both endpoints: `POST /hub/doses/scan`, `POST
   /hub/medications/{id}/skip`, `skips` in state.)** Earlier finding: the backend lacked the two Track endpoints. `POST /medications/{id}/skip` and `POST /doses/scan` return 404
   on the reference `tools/hub_adapter` (`{"detail":"Not Found"}`, verified), and the update from Sinchana says the
   same for Urvi's `/hub` (not verified by me). Contract: `frontend/docs/api-contract.md` ("Skip", "Dose match",
   `fixtures/dose-scan-*.json`). The adapter's `GET /state` also has no `skips` key. A wrong bottle must add a
   `wrong_bottle` event, and a skipped slot must not count as missed in `GET /adherence`. Until then Skip and
   the scanner show a clear "This hub can't ... yet" and everything else works (Mark as taken, Remind Rosa).
5. **Default branch history was rewritten.** `feat/inference-medcheck` was force-updated from `2637b78`
   to `d03fada` (after 2026-10-11T03:57Z) at the repo owner's request, to drop a co-author trailer from the
   first iOS commit. Everything up to Apollo's `b0489fe` is unchanged. Anyone who fetched the old tip must
   `git fetch && git reset --hard origin/feat/inference-medcheck`. Closed PR #2 still points at the old commit.
6. **Same code, two branch names.** `feat/frontend-ios` holds the earlier commits (`b78dee8`, `d5e922e`) this
   branch is built on. `feat/ios-aparajita` is canonical.
7. **No overlap with other components:** this branch only adds `ios/` and `docs/ios-aparajita.md`.

### I.8 OCR, OpenFDA and why a scan can read "the wrong medicine" (found 2026-10-11, real stack run locally)

- **Demo data answers scans without reading the photo.** The built-in demo hub returns scripted results (a "Lisinopril"
  scan, and "the dose that is due", Vitamin D3, on Track). Check the chip: it must not say "Demo data".
- **Gateway mode matters.** `MEDCHECK_API_MODE=mock` returns canned fixtures chosen by a hash of the image (Metformin,
  Amoxicillin, Ibuprofen "uncertain"). Real reading needs `.venv-full` (RapidOCR + ONNX Runtime, `scripts/setup_full_env.sh`)
  and `MEDCHECK_API_MODE=real`. Verified: real OCR reads a synthetic "FLUOXETINE 20 mg CAPSULES" label perfectly.
- **Fluoxetine is not in `services/ocr/lexicon.py`** (Metformin and Sertraline are), so the gateway's name field falls
  back to a wrong word ("Pharmacy", 0.3). With `OPENFDA_ENABLED=true` the hub recovers "Fluoxetine" from OpenFDA, but
  only at confidence 0.80 = **unsure**, by design. `hub/verify.py` fails closed on an unsure name, so the Track scanner
  answers "not clearly enough to be sure" until the medication is **tracked**: after that the hub passes it as
  `known_candidates` and the scan matches ("Fluoxetine 20 mg", then `not_scheduled`/`match` by the clock).
  The durable fix is more names in the OCR lexicon (the OCR owner's file; not changed here).
- **Update (2026-10-11, same day): the OCR word list had only 41 drugs.** That was the cause of "reads the pharmacy name
  instead of the medicine": with the drug missing from `DRUG_NAMES`, the extractor's name field fell back to the biggest
  word on the label ("WALGREENSPHARMACY", 0.3) and, because the strength is only trusted at 0.9 when it sits beside a
  *recognized* name, the strength dropped to 0.75 = unsure as well. 125 common generics were added to
  `services/ocr/lexicon.py` (brand names were tried and removed: generic labels print "Generic for Prozac", and the brand
  was then read as the medicine) (OCR owner's file, changed on `feat/integrate-ios` only; the 164 OCR tests and 519 inference
  tests pass). A label that previously gave `WALGREENSPHARMACY` / 0.3 now gives `Fluoxetine` 0.95 and `20 mg` 0.9.
- **Name consistency matters.** The hub only accepts an exact name match (`test_17`: "Metformin HCl" is *not* the tracked
  "Metformin", by the backend owner's design, and unsure names or strengths are never identity, `test_02`/`test_04`).
  A medication added earlier as "Fluoxetine Hcl" will therefore not match a bottle that now reads "Fluoxetine": stop
  tracking it and add it again. Whether salt suffixes should count as the same medicine is the backend owner's call.
- **Dose scanner compared against stopped medications.** `hub/dose_scan.today_events` looked at every open dose event of the
  patient, including doses of medications no longer tracked (here the seed's superseded Lisinopril 07:00 dose, still open
  until 19:00), so a correct scan was answered "Lisinopril is due now. Put this one back". It now only considers tracked
  medications (test `test_dose_scan_ignores_doses_of_stopped_medications`; backend 138 pass).
- **`/hub/health` and the app never fall back to demo silently**; a real hub that is unreachable shows the red chip.

### I.10 Demo-names mode (2026-10-11)

For the demo only four medicines are used, and the label reader must never mistake them or take a pharmacy or store
name ("University Pharmacy", "Amazon Basic Care") as the drug. With `HUB_ENABLED=true HUB_DEMO_NAMES=true` the hub
(`backend/app/hub/demo_names.py`) only ever names **Fluoxetine HCl, Fexofenadine, Vitamin D3 or Tylenol**, found
anywhere in the OCR text (aliases: prozac, allegra, cholecalciferol, acetaminophen; long names tolerate OCR noise such
as "Fexofenainein"). A label without one of them gets no name (the caregiver is asked for another photo). The strength is
taken from mg/mcg/IU on the label (never "303 G" from an address), preferring the tracked one when the label prints two
("25 mcg (1000 IU)"); a different strength is kept as printed so a wrong-strength bottle is still caught. Off by default.
Tests: `test_demo_names_*` (backend 140 pass). Verified on the live hub with synthetic labels of all four plus a decoy.
The tracked names in the demo database were renamed to match exactly ("D3" -> "Vitamin D3", "Fluoxetine Hcl" ->
"Fluoxetine HCl").

## J. Outstanding work

| # | Task | Status |
|---|---|---|
| 0 | Backend adds `POST /doses/scan` and `POST /medications/{id}/skip`; then rerun the live test and try a real scan | needs Urvi / orchestrator |
| 1 | ~~Run the live test against Urvi's `/hub`~~ | done (see H). Re-running it on the same DB makes "Contract Test" a duplicate (409 "already being tracked"); it writes counts, refills, settings |
| 2 | Reinstall the contract-conforming build on the iPhone 15 and run it against a hub on the LAN | next (needs the hub bound to a LAN/Tailscale address) |
| 3 | Real-device test of Track and the dose scanner: camera sheet, capture, a real bottle through the hub | not started |
| 4 | ~~Dosage-form-aware labels, patient/caregiver names~~ | done (fourth milestone); "Rosa" elsewhere stays hard-coded like web |
| 5 | Decide "Ask Rosa to scan again" (needs a backend endpoint or removal from the design) | needs team input |
| 6 | App icon, VoiceOver pass, dark mode | before demo if time |

Before the demo: items 1–3, with the hub reachable from the phone's network.

## K. Development change log

| When | Change | Why / notes | Commit |
|---|---|---|---|
| 2026-10-10 | Inspected project (empty Hello-world template, file-system-synchronized group) and unpacked the web wireframe bundle + iOS handoff | build the native app from the design | n/a |
| 2026-10-10 | Design system, Home, medication sheet, Scan/Verify/Preview/Added, History, Settings, mock hub, API layer, camera | first full UI + demo data | `b78dee8` |
| 2026-10-10 | Info.plist usage strings via build settings; display name MedCheck | camera / photos / local network prompts | `b78dee8` |
| 2026-10-10 | Debug launch args + 40-check self-test; iPad + AX Dynamic Type fixes; camera restart on appear | QA without a UI test target | `b78dee8` |
| 2026-10-10 | Deployment target 27.0 → 18.0 | install on iPhone 15 / iOS 18.5 | `b78dee8` |
| 2026-10-11 | Fix SonarCloud: 1 bug (`? 2 : 2`) and 39 smells; remove concurrency warnings | quality gate "Reliability rating" | `d5e922e` |
| 2026-10-11 | Pushed to `feat/frontend-ios`; PR #2 merged into `feat/inference-medcheck` carrying the first commit | | `3783248` (superseded) |
| 2026-10-11 | History of `feat/inference-medcheck` rewritten to remove a co-author trailer (see I.5) | owner request | `d03fada` |
| 2026-10-11 | Created `feat/ios-aparajita`; added this handoff; read the shared hub contract and recorded the mismatches | team handoff process | `b503d96`, `1f83520` |
| 2026-10-11 | **Conformed the client to the shared hub contract** (commit `b42266c`): new `HubContract.swift` (DTOs + mapping), rewritten `LiveAPI`, scan keys renamed to the nine contract keys, `reminded` dose state, `PATCH` edit limited to five fields, camera pause/resume via settings, `{detail}` errors surfaced, tolerant id/list decoding, rescan hidden on real hubs | the client had been written from the iOS handoff table, which did not match the hub | see "Pushed SHAs" |
| 2026-10-11 | Shrank the supply-shelf bottles by 25% (one scale constant) and tightened column spacing 20 → 12 pt | only 1.5 bottles were visible on an iPhone; the team wants at least two | see "Pushed SHAs" |
| 2026-10-11 | Added Debug-only `-medcheck.snapshot 1` (writes `Documents/medcheck-snapshot.png`) to screenshot a physical device; used it to confirm two bottles on the iPhone 15 | simulator widths are not a substitute for the real device | see "Pushed SHAs" |
| 2026-10-11 | **Track tab and dose scanner** (commit `8e8df9d`) from `MedCheck-iOS-Update.md`: `DayDoses` (port of `buildDay`), raw dose/skip/reminder records in `HubState`, `DoseStatus` now taken / skipped / late / reminded / missed / upcoming, `skipDose` and `matchDose` in the API, `method: "scan"`, `TrackView`, `TrackDoseRow`, `DoseScannerCard`, shared `CameraViewfinder` and `ScanSourcePicker` extracted from `ScanView`, Home's Track button, `MockHub` rebuilt on records with skip, scanner and double-dose rules | the web app added Track; the iOS app is meant to match it | see "Pushed SHAs" |
| 2026-10-11 | Added Debug contract tests (`-medcheck.fixtures`, `-medcheck.liveTest`); ran them against `tools/hub_adapter` | prove conformance instead of assuming it | see "Pushed SHAs" |

| 2026-10-11 | **Parity with `feat/integrate-track-tab`**: `VerificationCard` + "Log this dose now"; dosage-form chooser and form-aware copy; `schedule_times` in Edit details; `dosage_form` in `complete`, `warnings` shown; `medication_id: null` on a wrong bottle; null `pills_left` and fractional `dose_amount` no longer drop a medication; tolerant settings decoding; names from `state.patient`; alerts capped at 5 with empty text; settings validation before autosave; Hub connection card in all builds with `/hub` discovery; `NSAllowsLocalNetworking`; scan GET asks the hub like web; demo hub applies the real hub's completion rules | the app had been built from the shared contract only; the integrated hub sends more and is stricter | see "Pushed SHAs" |

| 2026-10-11 | **Track shows the live camera in the card** (no "open camera" sheet), and on iPhone the scanner comes right after the progress card; the status chip says **"Demo data. No hub connected."** in demo mode (it used to say "Connected to Rosa's hub", which hid that scans were scripted); hub `warnings` (objects `{code, medication, message}`) are decoded and shown | a tester on the phone was still on demo data and saw "Vitamin D3" for every bottle | see "Pushed SHAs" |
| 2026-10-11 | **Red "Don't take this yet" advisory** in the dose scanner: a tracked medicine scanned before its time (hub `not_scheduled` with a `medication_id`), one with no doses left today, and an unknown or wrong-strength bottle with nothing due now show a red tile with the hub's own sentence, a warning haptic and a hand icon, instead of the calm blue "Nothing due". Demo hub now uses the real hub's half-hour due window; self-test 108/108 | a caregiver scanned fluoxetine at 5 a.m. (due 8:30) and got a neutral "Nothing due" | see "Pushed SHAs" |
| 2026-10-11 | **App icon**: `AppIcon-1024.png` (the web's pink heart-pill) as the app icon (`Assets.xcassets/AppIcon`, `ASSETCATALOG_COMPILER_APPICON_NAME`) and as a 30 pt logo beside "MedCheck" in the top bar (`BrandIcon`, 192 px copy) | match the web app's branding | see "Pushed SHAs" |
| 2026-10-11 | **Reverted the patient/caregiver mode and live pop-ups** at the owner's request (the iOS app is back to the single caregiver dashboard). The backend still saves skipped and missed doses as hub events (migration `0006_hub_event_types`), and the web labels them; the iOS Home lists them under "Mistakes caught". The reverted work is commit `49c2efd` on this branch (`2029aab` on `feat/ios-aparajita`) and can be restored with `git revert` of the revert | the owner reported that adding a prescription stopped working after the change | see "Pushed SHAs" |

### Pushed SHAs

- `feat/ios-aparajita`: `b503d96` (handoff), `1f83520` (records that SHA), both docs-only on top of `d5e922e`.
- Contract-conformance milestone (code + docs): `b42266c`, verified on GitHub as the tip of `feat/ios-aparajita` on 2026-10-11.
- Track tab and dose scanner (code + docs): `8e8df9d`, verified on GitHub as the tip of `feat/ios-aparajita` on 2026-10-11.
- Parity with `feat/integrate-track-tab` (code + docs): `7548aae`, verified on GitHub as the tip of `feat/ios-aparajita` on 2026-10-11.
- Earlier: bottles at 75% and device snapshot `f57851a`, `c869e8d`.
- The docs-only commit that records these lines has its own SHA; `git log feat/ios-aparajita` is authoritative.
