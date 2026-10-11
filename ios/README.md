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

To use a real hub set `MEDCHECK_API_URL` in the scheme (see the handoff, sections E and J, before relying
on this: the client does not yet match the shared contract).

## Debug builds only

- Home ends with a **Demo bar** (Skip 1 day, Skip a week, Reset demo); Settings ends with a **Hub
  connection** card (demo data on/off, address, simulate offline).
- Launch arguments jump straight to a screen:

```
xcrun simctl launch booted <bundle id> \
  -medcheck.tab history          # home | scan | history | settings
  -medcheck.openMedication 1     # medication sheet
  -medcheck.verify 1             # Verify for the pending Lisinopril scan
  -medcheck.preview 1            # ...with fields filled and Preview open
  -medcheck.added 1              # Added screen
  -medcheck.skipDays 7           # move the demo clock
  -medcheck.offline 1            # hub unreachable
  -medcheck.scrollY 900 / -medcheck.sheetScrollY 500
```

- `-medcheck.selfTest 1` runs 40 checks of the store and demo hub and prints `SELFTEST PASS/FAIL` lines
  (read them with `xcrun simctl launch --console-pty`).

## Layout

`frontendmobileapp/` holds `Design/`, `Models/`, `Services/` (API protocol, live and demo clients, store,
camera), `Screens/` and `Fonts/` (Atkinson Hyperlegible, SIL OFL). Details in the handoff, section F.
