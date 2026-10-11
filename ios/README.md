# MedCheck iOS app

SwiftUI, minimum iOS 18.0, no third-party packages. Built from `docs/MedCheck-iOS-Handoff.md` and the
web wireframes. The app runs on demo data by default, so it works with no hub on the network.

## Run it

Open `ios/frontendmobileapp.xcodeproj`, pick an iPhone or iPad simulator, press Run.

**On a physical iPhone:** in Signing & Capabilities choose your own Team (and a bundle ID that is unique
to you if Xcode says it is taken), turn on Developer Mode on the phone, then Run. The first launch needs
Settings, General, VPN & Device Management, then Trust. The Team ID and bundle ID committed here are the
original author's, so expect to change them.

| Mode | How |
|---|---|
| Demo data (default) | Nothing to do. Same data as the web demo, today is Sat, Oct 10, 2026. |
| Real hub | Set the environment variable `MEDCHECK_API_URL` (for example `http://192.168.1.20:8000`) in the scheme, **or** in a Debug build open Settings, scroll to *Hub connection*, turn off *Use demo data* and enter the address. |

In Debug builds the Home screen ends with the **Demo bar** (Skip 1 day, Skip a week, Reset demo), and
Settings ends with a **Hub connection** card, including a switch that makes the demo hub look offline.
Neither is compiled into Release.

## Layout of the code

```
frontendmobileapp/
  MyApp.swift, ContentView.swift      entry point, 4-tab TabView (Home, Scan, History, Settings)
  Design/                             tokens, Atkinson font, CapsuleButtonStyle, shared components, PillBottleView + SupplyShelf
  Models/                             wire models, formatting, scan field keys
  Services/
    MedCheckAPI.swift                 the contract (protocol) + JSON/date coding
    LiveAPI.swift                     URLSession client for the FastAPI hub
    MockAPI.swift, MockHub.swift      in-memory hub seeded with the web demo data
    AppStore.swift                    single source of truth, polling, actions, derived copy
    CameraService.swift               AVFoundation behind a CameraSource protocol, Vision sharpness hint
    Router.swift, AppConfig.swift
  Screens/                            Home, Medication sheet, Scan / Verify / Preview / Added, History, Settings
  Fonts/                              Atkinson Hyperlegible Regular and Bold (SIL OFL, license included)
```

Screens only talk to `AppStore`; `AppStore` only talks to a `MedCheckAPI`. Swapping demo for live
changes nothing in the UI, the same idea as `client.js` on the web.

## API contract

> **To reconcile:** this table and the shapes below were written from the iOS handoff, before comparing
> with the web app's real contract in `frontend/docs/api-contract.md` and `frontend/docs/fixtures/`.
> Field names that differ should be fixed in `Models/Models.swift` (decoding is lenient, so mismatches
> show up as missing data rather than crashes).

Everything below is called through `MedCheckAPI`. Keys are snake_case, dates ISO 8601 (with or without
time zone). Decoding is lenient: missing collections become empty and unknown enum values fall back.

| UI | Call | Notes |
|---|---|---|
| Hub chip | `GET /health` | `{ "ok": true }`. Polled with `/state` every 5 s while Home is visible. |
| Home | `GET /state` | `medications`, `today`, `pending_scans`, `alerts`, `events`, optional `now` |
| Medication sheet | `GET /medications/{id}` | `{ medication, label_fields[{key,label,value,state}], week_taken, week_due }` |
| Recent doses, day breakdown | `GET /doses?medication_id=` / `?date=YYYY-MM-DD` | array (or `{doses:[]}`) of dose slots |
| Log a dose | `POST /medications/{id}/doses` | `{}` |
| Correct pill count | `POST /medications/{id}/counts` | `{ "count": 12 }` |
| Mark refill picked up | `POST /medications/{id}/refill` | `{}` |
| Scan, first photo | `POST /scans` | multipart, field name `image`, JPEG. Returns a scan |
| Scan, more photos | `POST /scans/{id}/photos` | multipart. Returns fields found so far |
| Verify | `GET /scans/{id}` | scan with `fields`, `events`, optional `label_image_url` |
| Add (Preview sheet) | `POST /scans/{id}/complete` | `{ "fields": [{key, value, state}] }`. Called exactly once |
| History | `GET /adherence?month=2026-10` | days with `due`, `taken`, `missed` |
| Settings | `GET /settings`, `PUT /settings` | autosaved 0.7 s after the last change |
| Privacy | `POST /camera/pause`, `GET /export`, `DELETE /data` | |
| Demo bar | `POST /demo/advance` (`{days}`), `POST /demo/reset` | |

### Shapes the handoff did not spell out

These are what the app sends and expects. Adjust either side, the changes are one file
(`Models/Models.swift` or `Services/LiveAPI.swift`).

- **Dose slot** (`today` in `/state`, and `/doses`): `medication_id`, optional `medication_name` and
  `strength`, `scheduled_at`, `status` (`taken` | `not_taken` | `upcoming`), optional `taken_at`, `method`
  (`voice` | `button` | `dashboard`). A `not_taken` slot on an earlier day is shown as "Missed".
- **Scan**: `id`, `status` (`reading` | `asking_patient` | `needs_caregiver` | `complete`), `fields`
  (keys `name`, `strength`, `instructions`, `dose_amount`, `dose_times`, `quantity`, `refills`,
  `pharmacy`, `pharmacy_phone`, `prescriber`; `state` is `filled` | `unsure` | `missing`), `photo_count`,
  `events[{kind: scanned|asked|unsure|sent, at, note}]`.
- **Medication** adds optional `prescriber_phone` (target of "Call Dr. Okafor's office"), `purpose`
  ("cholesterol") and `instructions`.
- **Settings**: `caregivers[{id,name,phone,scope: all|refills,is_you}]`, `first_reminder_days`,
  `second_reminder_days`, `urgent_days`, `text_missed_doses`, `text_no_refills`, `text_wrong_bottle`,
  `remind_again` (`30_minutes` | `1_hour` | `never`), `voice_language` (`en` | `es` | `pt`).
  The status thresholds on Home come from here, not from constants.
- **Adherence month**: `month`, `doses_due`, `doses_taken`, `days[]`, optional `missed_note`
  ("All three missed doses were in the evening.") and `suggestion` (the "Something to try" card).

### Buttons in the design with no endpoint in the handoff table

They are wired to the endpoints below so the buttons are not dead. Please confirm or replace.

| Button | Assumed call |
|---|---|
| Remind Rosa | `POST /medications/{id}/remind` |
| Ask Rosa to scan again | `POST /scans/{id}/rescan` |
| Discard (Verify) | `DELETE /scans/{id}` |
| Enter the details by hand | `POST /scans` with `{ "manual": true }`, returns an empty scan |
| Edit details | `PUT /medications/{id}` (full medication) |
| Stop tracking | `DELETE /medications/{id}` |

## Design decisions worth knowing

- **No Medications tab.** Per the handoff, a bottle opens the medication sheet. The old PDF still shows
  that tab; the HTML bundle and handoff are the newer source.
- **Greeting follows the clock** ("Good afternoon, Elena" at the demo clock's 2:20 PM). The web hard-codes
  "Good morning".
- **Light mode only** for now, as the handoff says dark variants come later.
- **Dynamic Type is not capped** in content. Two deliberate exceptions: the pinned top bar stops growing
  at the largest non-accessibility size, and the History calendar becomes a list of days at accessibility
  sizes because a seven-column grid cannot hold text that large.
- **Camera.** Back wide camera with continuous autofocus; Vision runs on preview frames to drive
  "Text is sharp. Hold still." Where there is no camera (Simulator), Take photo uses a generated sample
  label so the whole flow can be demoed. Permission strings are set in the target's build settings.
- **Home shows only scans Rosa handed over** under "Needs your help". A scan the caregiver started from
  the Scan tab is theirs already and is excluded.

## What differs from a fresh Xcode project

Build settings in `project.pbxproj`: `IPHONEOS_DEPLOYMENT_TARGET` is 18.0 (the template said 27.0, which
blocks iOS 18 phones), plus `INFOPLIST_KEY_CFBundleDisplayName` (MedCheck),
`INFOPLIST_KEY_NSCameraUsageDescription`, `INFOPLIST_KEY_NSPhotoLibraryUsageDescription` and
`INFOPLIST_KEY_NSLocalNetworkUsageDescription`, in both Debug and Release.
New files live inside the synchronized `frontendmobileapp/` folder, so they belong to the target
automatically. `ContentView` lost its Hello-world stub and `#Playground` scratch block.

## QA tools (Debug builds)

Launch arguments jump straight to a screen, handy for screenshots:

```
xcrun simctl launch booted <bundle id> \
  -medcheck.tab history          # home | scan | history | settings
  -medcheck.openMedication 1     # medication sheet
  -medcheck.verify 1             # Verify for the pending Lisinopril scan
  -medcheck.preview 1            # ...with the fields filled and Preview open
  -medcheck.added 1              # Added screen
  -medcheck.skipDays 7           # move the demo clock
  -medcheck.offline 1            # hub unreachable
  -medcheck.scrollY 900 / -medcheck.sheetScrollY 500
```

`-medcheck.selfTest 1` runs 40 checks of the store and demo hub (statuses, headline copy, scan flow,
refill and count math, offline, demo clock, adherence numbers) and prints `SELFTEST PASS/FAIL` lines;
read them with `xcrun simctl launch --console-pty`.

## Not done

WebSocket updates (Home polls instead), Meta AI glasses (disabled option, `CameraSource` is the seam),
dark mode, app icon, localization, and unit/UI test targets (the self-test above covers the logic).
