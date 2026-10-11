# iOS app handoff — Aparajita

> Single handoff file for the iOS component. Branch: `feat/ios-aparajita`. Code lives in [`ios/`](../ios/).
> Last updated: 2026-10-11. Status vocabulary: **verified** (I ran it and saw the result),
> **unverified** (written but not run/observed), **not built**.

## Current state in one paragraph

A native SwiftUI iPhone/iPad app that mirrors the caregiver web UI (Home, medication sheet, Scan → Verify →
Preview → Added, History, Settings). It **builds and runs on a real iPhone 15 (iOS 18.5) and in the
simulator, using built-in demo data**. The network client (`LiveAPI`) has **never been run against a real
server**, and as written it **does not match the shared hub contract** (`frontend/docs/api-contract.md`),
see section I. Conforming the client to that contract is the next task and is tracked in section J.

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
- **State:** UI feature-complete against the design and demo data; client/contract conformance pending.

## B. Implemented functionality

| Area | Status | Files |
|---|---|---|
| 4-tab app (Home, Scan, History, Settings), forced light mode | verified (simulator + iPhone 15) | `ContentView.swift`, `MyApp.swift` |
| Design system: tokens, gel-capsule buttons, status badges, pill bottle + supply shelf, Atkinson Hyperlegible | verified (visual) | `Design/*` |
| Home: headline from most urgent medication, needs-help card, shelf, today's doses, alerts, mistakes caught, privacy note, 5 s polling | verified (demo data) | `Screens/Home/*` |
| Medication sheet: stats, refill banner, call/copy, log dose, correct count, refill picked up, recent doses, label fields, edit, stop tracking | verified (demo data) | `Screens/Medication/MedicationSheet.swift` |
| Scan: camera preview with frame, sharpness hint, torch, photos strip, found-so-far, photo-library upload, manual entry, camera-blocked card | simulator verified (sample label, no camera); **real camera capture unverified** | `Screens/Scan/ScanView.swift`, `Services/CameraService.swift` |
| Verify → Preview → Add → Added flow with field states (filled / unsure / missing), edited-field badges, single-shot Add, inline failure | verified (demo data, self-test) | `Screens/Scan/*` |
| History: month calendar, day breakdown, suggestion, PDF report via share sheet | verified (demo data); share sheet unverified on device | `Screens/History/HistoryView.swift` |
| Settings: caregivers, thresholds, alert toggles, reminders, privacy actions, autosave | verified (demo data) | `Screens/Settings/SettingsView.swift` |
| iPad (regular width) layouts, Dynamic Type through AX XXL | verified in simulator | all screens |
| Demo data hub with clock controls (Skip day / week / Reset) | verified | `Services/MockHub.swift`, `MockAPI.swift` |
| Debug-only: demo bar, hub-connection card, launch args, 40-check self-test | verified | `Services/Debug*.swift` (`#if DEBUG`) |

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

### E2. What the iOS client sends today (`Services/LiveAPI.swift`)

All paths relative to the base URL (`MEDCHECK_API_URL`, or Debug-only Settings card). No auth header.

| Method | Path | Body |
|---|---|---|
| GET | `/health` | |
| GET | `/state` | |
| GET | `/medications/{id}` | |
| GET | `/doses?medication_id=` or `?date=` | |
| POST | `/medications/{id}/doses` | `{}` |
| POST | `/medications/{id}/counts` | `{"count": n}` |
| POST | `/medications/{id}/refill` | `{}` |
| POST | `/medications/{id}/remind` | `{}` |
| PUT | `/medications/{id}` | full medication |
| DELETE | `/medications/{id}` | |
| POST | `/scans` | multipart field **`image`**, or `{"manual": true}` |
| POST | `/scans/{id}/photos` | multipart field **`image`** |
| GET | `/scans/{id}` | |
| POST | `/scans/{id}/rescan` | `{}` |
| DELETE | `/scans/{id}` | |
| POST | `/scans/{id}/complete` | `{"fields":[{key,value,state}]}` |
| GET | `/adherence?month=2026-10` | |
| GET / PUT | `/settings` | settings |
| POST | `/camera/pause`, GET `/export`, DELETE `/data` | |
| POST | `/demo/advance` `{"days":n}`, `/demo/reset` | |

Date handling accepts ISO 8601 with or without a time zone and with or without fractional seconds.
Keys are decoded with `.convertFromSnakeCase`.

### E3. Contract mismatches (client vs `frontend/docs/api-contract.md`) — **all unresolved as of this commit**

| # | iOS client today | Hub contract | Effect if unchanged |
|---|---|---|---|
| 1 | `GET /state` decoded as `{medications, today[], pending_scans, alerts, events, now}` | `{now, patient, hub, medications, doses[], reminders[], alerts, events, scans[], settings}`. No `today` list: slots are derived from `schedule_times` + `doses` | Today's doses, needs-help card and settings come back empty |
| 2 | Dose slot `{medication_id, scheduled_at, status, taken_at, method}` | Dose `{id, medication_id, slot "HH:MM", date, taken_at, method}`; a past slot with no dose is "missed" | Taken/missed wrong |
| 3 | `GET /medications/{id}`, `GET /doses` | do not exist | 404; sheet loses label fields / recent doses |
| 4 | Event time key `occurred_at` | `at` | Event decode fails |
| 5 | Log dose body `{}` | `{"method":"dashboard","slot":"HH:MM"?}`; returns State | works only if server tolerates empty body |
| 6 | Remind body `{}` | `{"slot":"HH:MM"}` | wrong/ignored |
| 7 | Edit details `PUT /medications/{id}` full object | `PATCH` with only `instructions`, `quantity_start`, `refills_remaining`, `prescriber`, `pharmacy_phone` | 405/ignored; edit form also offers fields the hub cannot save |
| 8 | Photo upload field `image` | `photo` | upload rejected |
| 9 | Scan `fields` is an array; keys `dose_times`, `quantity`, `refills`, `pharmacy`, plus `instructions`; `photo_count`, `events` | `fields` is an object with exactly nine keys: `name, strength, dose_amount, schedule_times, quantity_start, refills_remaining, pharmacy_name, pharmacy_phone, prescriber`; values are strings; `photos`, `manual`, `created_at`, `history[{step,at,detail}]`. No `instructions` | scan screens show nothing |
| 10 | `POST /scans/{id}/rescan` ("Ask Rosa to scan again") | not in contract | 404; **needs a team decision** (see J) |
| 11 | Complete body `{"fields":[…]}` | flat object of strings with the nine contract keys; returns `{medication}`; 409 if already complete, 422 with readable `detail` | Add fails |
| 12 | Adherence `?month=2026-10` → `{month, doses_due, doses_taken, days[{date,due,taken,missed}], missed_note, suggestion}` | `{year, month (0-based), due, taken, missed, days[{date,due,missed,future,missedList[{medication_id,name,slot}]}]}`; insight text is computed by the client | History empty |
| 13 | `GET /settings`, snake fields `first_reminder_days…`, `remind_again` `30_minutes`… | settings only inside State: `thresholds{first,second,urgent}`, `alert_missed`, `alert_no_refills`, `alert_wrong_bottle`, `remind_again` `"30"|"60"|"never"`, `voice_language` `"English"…`, `camera_paused`, `caregivers[{id,name,phone,scope,you}]`; `PUT /settings` returns State | settings never load/save |
| 14 | `POST /camera/pause` | `PUT /settings` with `camera_paused: true` | 404 |
| 15 | Errors shown as a generic sentence | `{"detail": "..."}` is meant to be shown to the caregiver | less helpful messages |

Endpoints that already match: `GET /health`, `POST …/counts`, `POST …/refill`, `DELETE /medications/{id}`,
`DELETE /scans/{id}`, `GET /export`, `DELETE /data`, `POST /demo/advance`, `POST /demo/reset`,
`POST /scans` with `{"manual": true}`, `POST /scans/{id}/photos` path.

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
| Point at a hub | set `MEDCHECK_API_URL=http://<host>:8000/hub` in the scheme (or `:8500` for `hub_adapter`) | **unverified** (client does not match contract yet) |
| In-app self-test (40 checks) | `xcrun simctl launch --console-pty booted <bundle id> -medcheck.selfTest 1` | verified, 40/40 against `MockAPI` |

Environment: macOS with Xcode 27. Device: Developer Mode on, device trusted, a development Team selected
(the Team ID and bundle ID committed in `project.pbxproj` are Aparajita's personal ones, not secrets, but
change them). Debug launch arguments are listed in `ios/README.md`.

## H. Testing and verification

| Item | Result |
|---|---|
| Simulator build (iPhone 17, iOS 27 runtime) | passes, 0 warnings (2026-10-11) |
| macOS build | passes |
| Generic iOS device compile at min iOS 18.0 | passes |
| Signed build installed and launched on iPhone 15 (`iPhone15,4`, iOS 18.5) | passes; Aparajita reported it "looks good" |
| In-app self-test | 40/40 (statuses, headline copy, bottle pill counts, scan flow, refill and count maths, offline, demo clock, adherence numbers, settings round trip) |
| Visual QA | iPhone 17, iPhone 17e, iPad Pro 11" simulators; AX XXL text; offline chip |
| SonarCloud | 1 bug + 39 smells reported on the first push; all 40 fixed in `d5e922e` (new analysis not yet seen) |

**Not tested:** real camera capture and the sharpness hint on a device; share sheets on a device; tel: call;
Local Network prompt; **any request against a real hub, `/hub` or `hub_adapter`**; VoiceOver pass; Reduce
Motion; Release configuration; iPad on hardware; no XCTest or UI tests exist.

**Known failures:** none in what is tested. Known *gaps* are in sections E3 and J.

## I. Integration-relevant issues

1. **Contract mismatch (section E3).** The client was written from the iOS design handoff's endpoint table,
   which differs from the shared hub contract. Needs conforming before any integration test.
2. **No `rescan` endpoint** in the contract for "Ask Rosa to scan again". Proposal: hide the button until
   the backend adds one, or map it to a reminder/ask event if Urvi defines one.
3. **Edit details can only persist five fields** (`instructions`, `quantity_start`, `refills_remaining`,
   `prescriber`, `pharmacy_phone`). The current form offers more.
4. **`/hub` is unauthenticated** and bound to localhost in the documented commands. A phone needs it reachable
   on the LAN or Tailscale. Either bind to a LAN address for the demo or add a token (would need Urvi's and
   Sinchana's agreement).
5. **Default branch history was rewritten.** `feat/inference-medcheck` was force-updated from `2637b78`
   to `d03fada` (after 2026-10-11T03:57Z) at the repo owner's request, to drop a co-author trailer from the
   first iOS commit. Everything up to Apollo's `b0489fe` is unchanged. Anyone who fetched the old tip must
   `git fetch && git reset --hard origin/feat/inference-medcheck`. Closed PR #2 still points at the old commit.
6. **Same code, two branch names.** `feat/frontend-ios` holds the same commits (`b78dee8`, `d5e922e`) that
   this branch is built on. `feat/ios-aparajita` is the canonical branch from now on; the older one can be
   ignored.
7. **No overlap with other components:** this branch only adds `ios/` and `docs/ios-aparajita.md`.

## J. Outstanding work

| # | Task | Status |
|---|---|---|
| 1 | Conform `LiveAPI` + models to the hub contract (E3 rows 1–15), keeping `MedCheckAPI` and screens unchanged where possible | **next, in progress** |
| 2 | Decode every `frontend/docs/fixtures/*.json` in the self-test to prove the mapping | next |
| 3 | Run the app against `/hub` or `hub_adapter` from the simulator, then from the iPhone | blocked on 1 |
| 4 | Real-device camera test (preview, sharpness hint, torch, capture, upload) | not started |
| 5 | Reduce "Edit details" to the five fields the hub can save | with 1 |
| 6 | Decide "Ask Rosa to scan again" | needs team input |
| 7 | App icon, VoiceOver pass, dark mode | before demo if time |

Before the demo: items 1–4 at minimum, plus the hub reachable from the phone's network.

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
| 2026-10-11 | Created `feat/ios-aparajita`; added this handoff; read the shared hub contract and recorded the mismatches (E3) | team handoff process | see "Pushed SHAs" |

### Pushed SHAs

- `feat/ios-aparajita` base (code unchanged from `feat/frontend-ios`): `d5e922e`.
- Handoff commit `b503d96` (docs only): verified on GitHub as the tip of `feat/ios-aparajita` on 2026-10-11.
- A later docs-only commit that records this line carries a new SHA; `git log feat/ios-aparajita` is authoritative.
