# MedCheck iOS app: design and build handoff

This document describes everything needed to build the MedCheck caregiver app for iOS with the same look, components and behavior as the web app. The web designs live on the shared canvas; this file is the source of truth for colors, sizes, copy and behavior.

**Who it's for:** Elena, a caregiver checking on her mother Rosa, who has low vision and takes five daily medications. Caregivers are often older and often worried, so everything favors calm colors, large readable text and obvious actions.

**Recommended stack:** SwiftUI, iOS 17+, `async/await` networking, AVFoundation for the camera.

---

## 1. App structure

A `TabView` with four tabs. There is no Medications tab: everything about a single medication lives in a sheet that opens from its bottle on Home.

| Tab | SF Symbol | Purpose |
|---|---|---|
| Home | `house` | Status at a glance, supply shelf, today's doses, alerts |
| Scan | `camera.viewfinder` | Scan a pill bottle label to add a medication |
| History | `calendar` | Dose adherence by month |
| Settings | `gearshape` | Caregivers, alert thresholds, reminders, privacy |

Flows that sit on top of tabs:

- **Medication sheet**: opened by tapping a bottle cap on Home, or the "See Atorvastatin" button.
- **Verify, Preview, Added**: the second and third steps of the Scan flow, pushed in a `NavigationStack` inside the Scan tab.

---

## 2. Color tokens

Pastel blue throughout. Strong color is used only for text, never as a large fill. Add these to an asset catalog (with dark-mode variants later) or a `Color` extension.

### Brand and surfaces

| Token | Hex | Use |
|---|---|---|
| `sky` | `#9CC3EC` | Left half of primary capsules |
| `skyMid` | `#AACDF0` | Primary capsule blend stop |
| `iceMid` | `#BCD9F5` | Primary capsule blend stop |
| `ice` | `#D2E7FB` | Right half of primary capsules |
| `mist` | `#E8F1FC` | Selected tab fill, hover, info backgrounds |
| `page` | `#F5F9FD` | Screen background |
| `card` | `#FFFFFF` | Cards, sheets, secondary capsules |
| `line` | `#D8E3F0` | Borders and dividers |
| `lineSoft` | `#E4ECF5` | Row separators inside cards |
| `track` | `#EEF3F9` | Empty tracks, close-button fill |
| `primaryEdge` | `#7EA7D4` | The 3D edge under primary capsules |
| `secondaryEdge` | `#CBD9EA` | The 3D edge under secondary capsules |

### Text

| Token | Hex | Use |
|---|---|---|
| `navy` | `#1F3A68` | Button labels, headings, links, logo |
| `ink` | `#152238` | All body text (about 15:1 on white) |
| `inkSoft` | `#46546B` | Secondary text, captions, labels |
| `inkMuted` | `#66707F` | Disabled text only |

### Status

Each status has a pastel fill, a darker text color and a pill color. **Always pair a status color with words** ("2 days left", "Refill now"); never rely on color alone.

| Status | Fill | Tint (bottle glass, banners) | Text | Pill halves | Label |
|---|---|---|---|---|---|
| On track | `#DCF1E3` | `#E9F5ED` | `#22613B` | `#8FCFA5` / `#DCF1E3` | On track |
| Refill soon | `#FCEFCC` | `#FDF5DC` | `#6E4700` | `#F2CF6B` / `#FCEFCC` | Refill soon |
| Urgent | `#FBDCD6` | `#FDE8E4` | `#9A1F14` | `#EE9A8E` / `#FBDCD6` | Refill now |

Danger buttons (Delete, Call the doctor's office) use coral: blend `#F3B2AA → #FBDCD6`, text `#8A1C12`, edge `#DD968C`.

### Status rules

```
days_left = pills_left / (dose_amount × doses_per_day)

days_left ≤ 3   → urgent
days_left ≤ 7   → refill soon
otherwise       → on track
refills_remaining == 0 → show the "No refills left" banner regardless of days
```

The thresholds (7, 5, 3) come from Settings, so read them from the API rather than hard-coding.

```swift
import SwiftUI

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

enum MC {
    // Brand
    static let sky = Color(hex: 0x9CC3EC)
    static let skyMid = Color(hex: 0xAACDF0)
    static let iceMid = Color(hex: 0xBCD9F5)
    static let ice = Color(hex: 0xD2E7FB)
    static let mist = Color(hex: 0xE8F1FC)
    static let page = Color(hex: 0xF5F9FD)
    static let line = Color(hex: 0xD8E3F0)
    static let lineSoft = Color(hex: 0xE4ECF5)
    static let track = Color(hex: 0xEEF3F9)
    static let primaryEdge = Color(hex: 0x7EA7D4)
    static let secondaryEdge = Color(hex: 0xCBD9EA)
    // Text
    static let navy = Color(hex: 0x1F3A68)
    static let ink = Color(hex: 0x152238)
    static let inkSoft = Color(hex: 0x46546B)
    static let inkMuted = Color(hex: 0x66707F)
}

enum SupplyStatus {
    case onTrack, refillSoon, urgent

    var fill: Color { switch self {
        case .onTrack: Color(hex: 0xDCF1E3)
        case .refillSoon: Color(hex: 0xFCEFCC)
        case .urgent: Color(hex: 0xFBDCD6) } }

    var tint: Color { switch self {
        case .onTrack: Color(hex: 0xE9F5ED)
        case .refillSoon: Color(hex: 0xFDF5DC)
        case .urgent: Color(hex: 0xFDE8E4) } }

    var text: Color { switch self {
        case .onTrack: Color(hex: 0x22613B)
        case .refillSoon: Color(hex: 0x6E4700)
        case .urgent: Color(hex: 0x9A1F14) } }

    var pill: (Color, Color) { switch self {
        case .onTrack: (Color(hex: 0x8FCFA5), Color(hex: 0xDCF1E3))
        case .refillSoon: (Color(hex: 0xF2CF6B), Color(hex: 0xFCEFCC))
        case .urgent: (Color(hex: 0xEE9A8E), Color(hex: 0xFBDCD6)) } }

    var label: String { switch self {
        case .onTrack: "On track"
        case .refillSoon: "Refill soon"
        case .urgent: "Refill now" } }

    static func from(daysLeft: Double) -> SupplyStatus {
        daysLeft <= 3 ? .urgent : daysLeft <= 7 ? .refillSoon : .onTrack
    }
}
```

---

## 3. Typography

The web app uses **Atkinson Hyperlegible**, a typeface designed for low-vision readers. It's free (SIL Open Font License) from Google Fonts. Bundle the Regular and Bold weights and register them in `Info.plist` under `UIAppFonts`.

Map every style to a Dynamic Type text style with `Font.custom(_:size:relativeTo:)` so text grows with the user's accessibility settings. Do not cap Dynamic Type.

| Role | Size | Weight | Relative to | Example |
|---|---|---|---|---|
| Screen headline | 34 | Bold | `.largeTitle` | "Atorvastatin runs out in 2 days." |
| Section title | 20 | Bold | `.title3` | "Today's doses" |
| Sheet title | 26 | Bold | `.title2` | "Atorvastatin" |
| Big number | 24 | Bold | `.title2` | "29 days" |
| Body | 17 | Regular | `.body` | Most text |
| Button | 17 | Bold | `.headline` | "Log a dose" |
| Caption | 14 | Regular / Bold | `.footnote` | Times, labels, badges |

Copy is sentence case everywhere. No all-caps labels.

---

## 4. The capsule button (signature element)

Every button is a pill-shaped capsule that looks like a real gel capsule: rounded, softly shaded, with a faint ridge in the middle where the two halves meet. It should read as **one object**, not two pieces.

**Anatomy, bottom layer to top:**

1. **Shape:** `Capsule()`. Heights of 56pt (large) and 44pt (standard, the minimum tap target). Horizontal padding of 30pt and 20pt.
2. **Color blend:** a horizontal gradient from `sky` to `ice` with stops at 0%, 46%, 54% and 100%.
3. **Ridge:** a 1pt vertical line at the exact center, `navy` at 10% opacity, with a 1pt white line at 55% opacity directly to its right. Barely visible, it just suggests the capsule join.
4. **Shading:** a vertical gradient overlay: white at 60% at the top, fading to clear by 55%, then `ink` at 7% at the bottom. This is what makes it look round.
5. **Depth:** an inner shadow along the bottom (`ink` at 10%), a solid 3pt edge below in `primaryEdge`, and a soft drop shadow (`#6496D2` at 22%, radius 7, y 6).
6. **Pressed:** the button moves down 3pt and the solid edge disappears, so it visibly presses in.

| Variant | Blend | Label | Edge | Use |
|---|---|---|---|---|
| Primary | `#9CC3EC → #D2E7FB` | `navy` | `#7EA7D4` | One main action per screen: Add, Take photo, Preview, Done |
| Secondary | `#E6F0FB → #FFFFFF` | `navy` | `#CBD9EA` | Edit, Cancel, Correct pill count, Remind Rosa |
| Danger | `#F3B2AA → #FBDCD6` | `#8A1C12` | `#DD968C` | Delete all data, Call the doctor's office |
| Disabled | flat `#ECEFF4` | `inkMuted` | none | No shading, ridge or shadow, so it reads as off |

```swift
struct CapsuleButtonStyle: ButtonStyle {
    enum Kind { case primary, secondary, danger }
    var kind: Kind = .primary
    var large = false
    @Environment(\.isEnabled) private var isEnabled

    private var stops: [Color] {
        switch kind {
        case .primary: [MC.sky, MC.skyMid, MC.iceMid, MC.ice]
        case .secondary: [Color(hex: 0xE6F0FB), Color(hex: 0xEEF5FC), Color(hex: 0xF6F9FE), .white]
        case .danger: [Color(hex: 0xF3B2AA), Color(hex: 0xF6BFB7), Color(hex: 0xF8CDC6), Color(hex: 0xFBDCD6)]
        }
    }
    private var label: Color { kind == .danger ? Color(hex: 0x8A1C12) : MC.navy }
    private var edge: Color {
        switch kind {
        case .primary: MC.primaryEdge
        case .secondary: MC.secondaryEdge
        case .danger: Color(hex: 0xDD968C)
        }
    }

    func makeBody(configuration: Configuration) -> some View {
        let pressed = configuration.isPressed
        configuration.label
            .font(.custom("AtkinsonHyperlegible-Bold", size: large ? 18 : 17, relativeTo: .headline))
            .foregroundStyle(isEnabled ? label : MC.inkMuted)
            .padding(.horizontal, large ? 30 : 20)
            .frame(minHeight: large ? 56 : 44)
            .background {
                if isEnabled {
                    ZStack {
                        Capsule().fill(LinearGradient(
                            stops: [.init(color: stops[0], location: 0), .init(color: stops[1], location: 0.46),
                                    .init(color: stops[2], location: 0.54), .init(color: stops[3], location: 1)],
                            startPoint: .leading, endPoint: .trailing))
                        // Ridge where the two halves meet
                        HStack(spacing: 0) {
                            Rectangle().fill(MC.navy.opacity(0.10)).frame(width: 1)
                            Rectangle().fill(Color.white.opacity(0.55)).frame(width: 1)
                        }
                        // Rounded shading
                        Capsule().fill(LinearGradient(
                            stops: [.init(color: .white.opacity(0.6), location: 0),
                                    .init(color: .white.opacity(0.12), location: 0.38),
                                    .init(color: .clear, location: 0.55),
                                    .init(color: MC.ink.opacity(0.07), location: 1)],
                            startPoint: .top, endPoint: .bottom))
                    }
                    .clipShape(Capsule())
                    .background(Capsule().fill(edge).offset(y: pressed ? 0 : 3))
                    .shadow(color: Color(hex: 0x6496D2).opacity(pressed ? 0 : 0.22), radius: 7, y: 6)
                } else {
                    Capsule().fill(Color(hex: 0xECEFF4))
                }
            }
            .offset(y: pressed ? 3 : 0)
            .animation(.easeOut(duration: 0.1), value: pressed)
    }
}

// Usage
Button("Add") { add() }
    .buttonStyle(CapsuleButtonStyle(kind: .primary, large: true))
```

The pill theme carries into other controls: badges, the hub status chip, text fields, pickers and toggles are all capsule-shaped. Toggles use the primary blend when on and `lineSoft` when off, with a white knob.

---

## 5. Shared components

| Component | SwiftUI | Spec |
|---|---|---|
| `CapsuleButton` | `ButtonStyle` above | Primary, secondary, danger, disabled |
| `StatusBadge` | `Text` in a `Capsule` | Status fill, status text color, 14pt bold, padding 4×12 |
| `Card` | `VStack` with background | White, 16 to 18pt corner radius, 1pt `line` border, padding 18 to 22 |
| `SectionHeader` | `VStack(alignment: .leading)` | 20pt bold title plus a `inkSoft` helper line |
| `HubStatusChip` | Capsule | Connected: mint fill, green dot, "Connected to Rosa's hub". Offline: coral fill, "Can't reach the hub. Retrying." |
| `StatTile` | Rounded rect | `page` fill, 14pt radius, 14pt label over a 22 to 24pt bold value |
| `NoticeBanner` | Rounded rect | Status tint fill, bold title in the status text color, optional buttons |
| `EmptyState` | Centered text | "No doses logged today yet." plus a secondary capsule |
| `DemoBar` | Bottom bar | Navy background, "Demo mode. Today is Sat, Oct 10", Skip 1 day, Skip a week, Reset demo. Debug builds only |

---

## 6. Screens

### 6.1 Home

Scrolls vertically on the `page` background. Top to bottom:

1. **Greeting and headline.** "Good morning, Elena. Here's how Rosa is doing." Then one sentence about the most urgent issue, for example "Atorvastatin runs out in 2 days.", with an urgent badge such as "Urgent: no refills left". If everything is fine: "Every medication is stocked for at least a week."
2. **Primary actions.** "See Atorvastatin" (primary, opens that medication's sheet) and "Add medication" (secondary, jumps to the Scan tab).
3. **Needs your help** card, shown only when a scan is incomplete: "Finish adding Lisinopril. Rosa scanned a new bottle, but the tablet count and refills are missing. She couldn't add them by voice." Button: "Fill in 2 details", which opens Verify.
4. **Supply for the next 30 days** (the `SupplyShelf`, section 7).
5. **Today's doses.** "3 of 6 doses taken. Next: 8:00 PM." One row per scheduled dose: time, medication, and a status of taken ("Taken 8:14, by voice"), not taken yet (butter row with a "Remind Rosa" secondary capsule) or upcoming.
6. **Texts sent to you.** Alert rows with a status badge, the message and the time.
7. **Mistakes caught.** "Rosa picked up Metformin when Lisinopril was due. MedCheck stopped her before she took it."
8. **Privacy note.** "Camera images never leave Rosa's home. This page shows only what MedCheck read from labels and the doses it logged."

On iPhone, sections stack in one column. On iPad, Today's doses and the alerts column sit side by side.

### 6.2 Medication sheet (replaces the Medications tab)

Opens with `.sheet(item:)` and `.presentationDetents([.large])` when a bottle cap is tapped. It includes, top to bottom:

1. **Header:** a capsule swatch in the status pill colors, name and strength ("Atorvastatin 20 mg"), the schedule with its purpose ("1 tablet each evening at 8:00 PM, for cholesterol"), the status badge and a close (×) button.
2. **Four stat tiles in a 2×2 grid on iPhone, 4 across on iPad:** Pills left, Runs out, Refills left, This week. Urgent and low values use the status text color; "0" refills is always red.
3. **Notice banner when needed.** No refills: "No refills left. Ask Dr. Okafor to send a new prescription to CVS Pharmacy. This usually takes 1 to 3 days, so ask today." with "Call Dr. Okafor's office" (danger, opens `tel:`) and "Copy prescription details" (secondary). Over-the-counter and low: "Running low. Over the counter, so no prescription needed."
4. **Actions:** "Log a dose" (primary), "Correct pill count" (secondary, opens a small form: "How many pills are left?"), "Mark refill picked up" (secondary, only when supply is low).
5. **Recent doses:** the last four days; missed doses have a butter background and "Missed".
6. **From the label:** instructions, quantity, fill date, refills, pharmacy and phone, prescriber. Low-confidence fields have a butter background and "Hard to read. Please check."
7. **Footer:** "Edit details" and "Stop tracking" (secondary), and "Done" (primary, dismisses).

### 6.3 Scan

Step indicator at the top: "1. Scan the label", "2. Check the details", "3. Add to schedule".

- **Scan with:** a two-option picker. "Computer camera" is replaced on iOS by **"This phone"** (selected). "Meta AI glasses" is shown disabled with "Coming after the MVP. Rosa will just look at the bottle."
- **Camera view:** a live `AVCaptureVideoPreviewLayer` with a white rounded frame to aim at, a top hint ("Hold the label inside the frame") and live feedback at the bottom ("Text is sharp. Hold still." in a mint capsule). Below it, a large primary "Take photo" button and a flashlight toggle.
- **Photos of this bottle:** thumbnails of shots taken so far, plus a dashed "Next photo" slot. "Labels wrap around the bottle. Turn it slowly and take another photo until every detail is found."
- **Found so far:** each field with a status badge: found (mint), unclear (butter), not found yet (coral). Hint: "Try the back of the label, where the quantity is usually printed." Primary button: "Check the details".
- **Fallbacks:** "Upload a photo of the label" (`PhotosPicker`) and "Enter the details by hand".
- **Camera blocked:** "Camera is blocked. Allow camera access in Settings, then try again." with a button that opens the app's Settings page.
- **Privacy line:** "Photos go only to the MedCheck hub to be read, and are deleted once you add the medication."

### 6.4 Verify (partial scans)

Title: "Help Rosa finish adding Lisinopril". Subtitle: "MedCheck read most of the label, but 2 details are missing. Rosa couldn't add them by voice, so she needs your help."

- **Timeline** of four steps: Scanned, Asked Rosa, Rosa wasn't sure, Sent to you (highlighted, "Waiting for you now").
- **Label photo** with "Ask Rosa to scan again".
- **Form** of capsule-shaped fields in three states:
  - filled: white with a `line` border;
  - unsure: butter fill, amber border, "MedCheck couldn't read this clearly. Check it against the bottle.";
  - missing: coral fill, coral border, with a reason, for example "Missing. Needed to warn before Rosa runs out."
- **What MedCheck will do:** a short summary of reminders and alerts.
- Buttons: "Discard" (secondary) and **"Preview"** (primary, disabled until no required field is missing).

### 6.5 Preview (confirmation sheet)

Title: "Check Lisinopril before adding". Subtitle: "This is what MedCheck will save. Details you typed in are marked."

Summary rows, with "Added by you" or "Corrected by you" badges on edited fields, then an "After you add it" note: "Rosa gets her first reminder tomorrow at 8:00 AM. You'll get a text around Nov 2, when about a week of tablets is left."

Two buttons only: **Edit** (secondary, dismisses the sheet with all fields kept) and **Add** (primary, calls the API). Disable Add and show a spinner while the request is in flight so it can't be sent twice. On failure, keep the sheet open: "Couldn't add Lisinopril. The MedCheck hub didn't respond. Your details are kept, so try again."

### 6.6 Added

A mint circle with a check, "Lisinopril is added", "Rosa heard "Lisinopril is all set" on her wearable. Her first reminder is tomorrow at 8:00 AM." A summary card, then "Scan another bottle" (secondary) and "Back to home" (primary).

### 6.7 History

- **Summary:** "Rosa took 55 of 58 doses this month" and "All three missed doses were in the evening." Secondary button: "Download report for her doctor" (share sheet with a PDF).
- **Calendar:** month grid with previous and next buttons. Day cells are rounded: mint for all taken, butter for one or more missed (with "2 missed"), dashed outline for upcoming. Selected day has a blue ring. Legend below.
- **Day breakdown:** that day's doses using the same dose rows as Home.
- **Suggestion card:** "Evening doses are missed most often. A second reminder at 8:30 PM could help." with a link to reminder settings.

### 6.8 Settings

- **People who get texts:** "Only these people ever hear from MedCheck. Rosa chose them." Rows for each caregiver with their alert scope and an Edit capsule, then "Add a person".
- **When to text you:** three capsule number fields (7, 5, 3 "days left") and toggles: missed doses by more than 1 hour, prescriptions with no refills left, wrong bottles caught.
- **Rosa's reminders:** "Remind again if a dose is missed" (After 30 minutes, After 1 hour, Don't remind again) and "Voice language" (English, Spanish, Portuguese).
- **Privacy:** "Everything is processed on the hub in Rosa's home. Camera images are never saved." What MedCheck stores, then "Pause the camera", "Download Rosa's data" (secondary) and "Delete all data" (danger, with a confirmation alert).

---

## 7. Supply shelf and pill bottle (Home)

A white card titled "Supply for the next 30 days" with the helper text "Each bottle shows how many days of pills Rosa has left. A full bottle is 30 days or more. Tap a cap to see everything about that medication."

Bottles stand in a row, **sorted most urgent first**. On iPhone the row scrolls horizontally (`ScrollView(.horizontal)`) with about 2.5 bottles visible so it's clear there's more. A small left column reads "Days left" and "Runs out", aligned with the text under the bottles.

**`PillBottleView` anatomy, top to bottom:**

1. **Cap (tappable):** a white rounded rectangle, 152×38pt, top corners 12pt and bottom 6pt, with vertical ridges (alternating white and `#E9EFF7` stripes about 7pt and 3pt wide) and a 5pt `line` band along its bottom. It's a `Button` with the accessibility label "Open Atorvastatin" and opens the medication sheet.
2. **Neck:** 134×8pt, `#DFE8F3`.
3. **Body:** 140×214pt, top corners 10pt and bottom 24pt. Fill is the status **tint**, with a horizontal glass highlight (white 70% at the left edge to clear at 28%, clear until 72%, white 45% at the right edge) and a 2pt inner stroke in `navy` at 10%.
4. **Label:** a white rounded rectangle inset 10pt, 18pt from the top, 62pt tall, with a soft shadow, showing the name (16pt bold) and strength (13pt).
5. **Pills:** two-tone capsules, 24×12pt, in the **status** pill colors (left half the stronger color, right half the lighter), with a white highlight along the top. They fill from the bottom up in rows of 4, centered, with 4pt gaps.
   - `pill_count = ceil(min(days_left, 30) / 30 × 24)`, so 24 pills is 30 days or more.
   - Because colors follow status, a medication's pills turn green, then yellow, then red as it runs low.
6. **Under the bottle:** days left (26pt bold, status text color, for example "29 days"), the run-out date ("Sun, Nov 8") and a status badge.

Accessibility: combine each bottle into one element reading, for example, "Atorvastatin, 2 days left, runs out Monday October 12, refill now. Button. Opens details."

---

## 8. Data and API

The iOS app talks to the same FastAPI backend as the web app. Base URL is configurable (the hub's address on the local network).

| Method | Path | Used by |
|---|---|---|
| GET | `/health` | Hub status chip |
| GET | `/state` | Home: medications, today's doses, pending scans, alerts, events |
| GET | `/medications/{id}` | Medication sheet: label fields with per-field confidence |
| GET | `/doses?medication_id=` or `?date=` | Recent doses, history day breakdown |
| POST | `/medications/{id}/doses` | Log a dose |
| POST | `/medications/{id}/counts` | Correct pill count, body `{ "count": 12 }` |
| POST | `/medications/{id}/refill` | Mark refill picked up |
| POST | `/scans` | First photo of a new bottle (multipart image) |
| POST | `/scans/{id}/photos` | Each additional photo; returns fields found so far |
| GET | `/scans/{id}` | Verify screen |
| POST | `/scans/{id}/complete` | **Add** on the Preview sheet. Called exactly once |
| GET | `/adherence?month=2026-10` | History calendar and summary |
| GET, PUT | `/settings` | Settings screen |
| POST | `/camera/pause`, GET `/export`, DELETE `/data` | Privacy controls |
| POST | `/demo/advance`, `/demo/reset` | Demo bar (debug only) |

```swift
struct Medication: Codable, Identifiable {
    let id: Int
    var name: String
    var strength: String
    var doseAmount: Int
    var dosesPerDay: Int
    var scheduleTimes: [String]       // "08:00"
    var quantityStart: Int
    var pillsLeft: Double
    var fillDate: String?
    var refillsRemaining: Int?        // nil for over-the-counter
    var pharmacyName: String?
    var pharmacyPhone: String?
    var prescriber: String?

    var daysLeft: Double { pillsLeft / Double(max(doseAmount * dosesPerDay, 1)) }
    var status: SupplyStatus { .from(daysLeft: daysLeft) }
}

struct Dose: Codable, Identifiable {
    let id: Int
    let medicationId: Int
    let takenAt: Date
    let method: String                // voice, button, dashboard
}

struct Alert: Codable, Identifiable {
    let id: Int
    let medicationId: Int
    let type: String                  // low_7, low_5, low_3, no_refills
    let message: String
    let sentAt: Date
}

enum FieldState: String, Codable { case filled, unsure, missing }

struct ScanField: Codable {
    let key: String
    var value: String?
    var state: FieldState
}
```

Use `JSONDecoder.keyDecodingStrategy = .convertFromSnakeCase` and ISO 8601 dates. Poll `GET /state` every few seconds while Home is visible (or use a WebSocket if the backend adds one) so doses logged by the wearable appear live.

**Partial scan states** returned by the backend: `reading`, `asking_patient`, `needs_caregiver`, `complete`. No reminders or supply alerts start until a scan is `complete`.

---

## 9. Camera and wearable

- Use AVFoundation with the back wide camera, continuous autofocus, and `AVCapturePhotoOutput` for full-resolution stills. Label text is small, so sharpness matters more than speed.
- Optional live feedback: run `VNRecognizeTextRequest` on preview frames to drive the "Text is sharp. Hold still." hint before uploading.
- Add `NSCameraUsageDescription`: "MedCheck uses the camera to read pill bottle labels. Photos are sent only to your MedCheck hub and deleted after the medication is added." Add `NSPhotoLibraryUsageDescription` for the upload fallback.
- Keep the camera behind a `CameraSource` protocol (`func capturePhoto() async throws -> Data`), with the phone camera as the first implementation. The Meta AI glasses become a second implementation later, and nothing downstream (upload, Found so far, Verify) changes.

---

## 10. Accessibility checklist

- Every tap target is at least 44×44pt.
- All text uses Dynamic Type through `relativeTo:`; test at the largest accessibility sizes. The stat tile grid should drop from 4 columns to 2, and the bottle row keeps scrolling.
- Status is never shown by color alone; every colored element has words.
- Every icon-only button has an accessibility label ("Close", "Open Atorvastatin").
- Respect Reduce Motion: skip the press animation and sheet springiness.
- Sheets dismiss with a swipe and the close button, and VoiceOver focus returns to the cap that opened them.
- Check contrast: body text `ink` and labels `navy` on pastel fills all exceed 4.5:1. Don't put `inkSoft` on status fills for important text.

---

## 11. Demo data

Use the same data as the web demo so screenshots and pitches match. Today is Sat, Oct 10, 2026.

| Medication | Strength | Schedule | Pills left | Days left | Runs out | Refills | Status |
|---|---|---|---|---|---|---|---|
| Atorvastatin | 20 mg | 1 at 8:00 PM | 2 | 2 | Mon, Oct 12 | 0 | Refill now |
| Vitamin D3 | 1000 IU | 1 at 8:00 AM | 4 | 4 | Wed, Oct 14 | N/A (over the counter) | Refill soon |
| Metformin | 500 mg | 1 at 8:00 AM and 8:00 PM | 22 | 11 | Wed, Oct 21 | 1 | On track |
| Lisinopril | 10 mg | 1 at 8:00 AM | 29 | 29 | Sun, Nov 8 | 2 | On track |
| Amlodipine | 5 mg | 1 at 8:00 AM | 64 | 64 | Sun, Dec 13 | 3 | On track |

Caregivers: Elena (you), all alerts; Marco, refill alerts only. Pharmacy: CVS Pharmacy, (732) 555-0123. Prescribers: Dr. Patel, and Dr. Okafor for Atorvastatin.
