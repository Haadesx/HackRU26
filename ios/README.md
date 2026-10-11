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

### Using the real hub (backend `/hub`, as the web app does)

1. On the Mac, run the backend with `HUB_ENABLED=true HUB_PATIENT_EMAIL=<patient>` **bound to the network**
   (`gunicorn -b 0.0.0.0:8000 wsgi:app`; `scripts/run_ui_demo.sh` binds `127.0.0.1`, which a phone cannot reach)
   and the inference gateway on :8300. Allow incoming connections for it in the macOS firewall.
2. In the app: Settings, **Hub connection**, turn off *Use demo data*, type the Mac's address (for example
   `192.168.1.20:8000`, or its Tailscale `100.x` address) and press **Apply**. MedCheck tries the address and
   `<address>/hub` and keeps the one that answers `GET /health`. Allow the Local Network prompt on first use.
3. Or set `MEDCHECK_API_URL` in the scheme (`http://<host>:8000/hub`, or `http://<host>:8500` for the reference
   `tools/hub_adapter`).

`/hub` has no login: keep it on your own network. The client speaks the shared contract in
`frontend/docs/api-contract.md` plus the extras of `feat/integrate-track-tab` (bottle check, dosage form,
dose times); see the handoff, sections E, H and I.

## Debug builds only

- Home ends with a **Demo bar** (Skip 1 day, Skip a week, Reset demo). The **Hub connection** card in
  Settings is in every build; only its "simulate offline" switch is Debug-only.
- Launch arguments jump straight to a screen:

```
xcrun simctl launch booted <bundle id> \
  -medcheck.tab history          # home | scan | track | history | settings
  -medcheck.trackBack 3          # Track: start 3 days back (0 is today)
  -medcheck.scanDemo 3           # Track scanner: check as if medication id 3 were in view (0 = the one due)
  -medcheck.scanDemo -1          # ...a bottle the hub doesn't track (wrong bottle, no medication id)
  -medcheck.scanConfirm 1        # ...and press "Rosa took it" on a match
  -medcheck.verification due_now # attach a bottle check to demo scans: due_now | already_taken | not_due |
                                 #   wrong_medication | strength_mismatch | uncertain
  -medcheck.edit 1               # with openMedication: open Edit details
  -medcheck.openMedication 1     # medication sheet
  -medcheck.verify 1             # Verify for the pending Lisinopril scan
  -medcheck.preview 1            # ...with fields filled and Preview open
  -medcheck.added 1              # Added screen
  -medcheck.skipDays 7           # move the demo clock
  -medcheck.offline 1            # hub unreachable
  -medcheck.scrollY 900 / -medcheck.sheetScrollY 500
```

- `-medcheck.selfTest 1` runs 106 checks of the store and demo hub and prints `SELFTEST PASS/FAIL` lines
  (read them with `xcrun simctl launch --console-pty`).
- `-medcheck.fixtures <path to frontend/docs/fixtures>` decodes the shared contract fixtures through the
  real mapper (`CONTRACT PASS/FAIL`).
- `-medcheck.liveTest 1` with `SIMCTL_CHILD_MEDCHECK_API_URL=http://127.0.0.1:8500` drives the live client
  against a running hub (start the reference one with `HUB_MODE=demo python -m uvicorn
  tools.hub_adapter.app:app --port 8500` from a checkout that has `tools/hub_adapter`).

## Layout

`frontendmobileapp/` holds `Design/`, `Models/`, `Services/` (API protocol, live and demo clients, store,
camera), `Screens/` and `Fonts/` (Atkinson Hyperlegible, SIL OFL). Details in the handoff, section F.
