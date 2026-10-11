# MedCheck iOS app

Native SwiftUI caregiver app (iPhone and iPad, minimum iOS 18.0, no third-party packages).

**The single source of truth for this component is [`docs/ios-aparajita.md`](../docs/ios-aparajita.md):**
current state, API contract and known mismatches, setup commands with verification status, test results,
outstanding work and change log. This file only covers running and debugging.

## Run

Open `frontendmobileapp.xcodeproj`, pick a simulator, press Run. The app starts on built-in demo data
(same story as the web demo: today is Sat, Oct 10, 2026), so it needs no hub.

On a physical iPhone: choose your own Team and, if needed, a unique bundle ID in Signing & Capabilities;
enable Developer Mode on the phone; Run; then trust the developer profile under Settings, General,
VPN & Device Management. The Team ID and bundle ID committed in the project are Aparajita's.

To use a real hub set `MEDCHECK_API_URL` in the scheme to the hub's base URL: `http://<host>:8000/hub`
(backend `/hub`) or `http://<host>:8500` (`tools/hub_adapter`). The client speaks the shared contract in
`frontend/docs/api-contract.md`; see the handoff, sections E, H and I.

## Debug builds only

- Home ends with a **Demo bar** (Skip 1 day, Skip a week, Reset demo); Settings ends with a **Hub
  connection** card (demo data on/off, address, simulate offline).
- Launch arguments jump straight to a screen:

```
xcrun simctl launch booted <bundle id> \
  -medcheck.tab history          # home | scan | track | history | settings
  -medcheck.trackBack 3          # Track: start 3 days back (0 is today)
  -medcheck.scanDemo 3           # Track scanner: check as if medication id 3 were in view (0 = the one due)
  -medcheck.scanConfirm 1        # ...and press "Rosa took it" on a match
  -medcheck.openMedication 1     # medication sheet
  -medcheck.verify 1             # Verify for the pending Lisinopril scan
  -medcheck.preview 1            # ...with fields filled and Preview open
  -medcheck.added 1              # Added screen
  -medcheck.skipDays 7           # move the demo clock
  -medcheck.offline 1            # hub unreachable
  -medcheck.scrollY 900 / -medcheck.sheetScrollY 500
```

- `-medcheck.selfTest 1` runs 68 checks of the store and demo hub and prints `SELFTEST PASS/FAIL` lines
  (read them with `xcrun simctl launch --console-pty`).
- `-medcheck.fixtures <path to frontend/docs/fixtures>` decodes the shared contract fixtures through the
  real mapper (`CONTRACT PASS/FAIL`).
- `-medcheck.liveTest 1` with `SIMCTL_CHILD_MEDCHECK_API_URL=http://127.0.0.1:8500` drives the live client
  against a running hub (start the reference one with `HUB_MODE=demo python -m uvicorn
  tools.hub_adapter.app:app --port 8500` from a checkout that has `tools/hub_adapter`).

## Layout

`frontendmobileapp/` holds `Design/`, `Models/`, `Services/` (API protocol, live and demo clients, store,
camera), `Screens/` and `Fonts/` (Atkinson Hyperlegible, SIL OFL). Details in the handoff, section F.
