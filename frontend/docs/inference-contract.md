# Inference contract: label reading, pill counting and the wearable

The web app never calls models directly. Everything goes through the backend:

```
camera or glasses ──photo──▶ backend ──image──▶ inference ──fields + confidence──▶ backend ──scan──▶ UI
wearable events (doses, wrong bottle, pill counts) ──▶ backend ──/state──▶ UI
```

So the inference code only has to produce the results below and hand them to the backend.
The UI already displays all of them.

## 1. Reading a pill bottle label

**Input:** one JPEG per call (from the webcam today, the Meta glasses later). A bottle usually
takes 2 to 3 photos because the label wraps around it.

**Output per photo:** for each of the nine fields, a value and a confidence from 0 to 1.

```json
{
  "name":              { "value": "Losartan", "confidence": 0.97 },
  "strength":          { "value": "25 mg",    "confidence": 0.95 },
  "dose_amount":       { "value": "1",        "confidence": 0.90 },
  "schedule_times":    { "value": "08:00",    "confidence": 0.70 },
  "quantity_start":    { "value": null,       "confidence": 0 },
  "refills_remaining": { "value": null,       "confidence": 0 },
  "pharmacy_name":     { "value": "CVS Pharmacy",   "confidence": 0.93 },
  "pharmacy_phone":    { "value": "(732) 555-0123", "confidence": 0.88 },
  "prescriber":        { "value": "Dr. Pat?l",      "confidence": 0.62 }
}
```

### Field rules

| Field | Format the UI expects | Notes |
|---|---|---|
| `name` | `"Losartan"` | Brand or generic as printed |
| `strength` | `"25 mg"`, `"1000 IU"` | Number, space, unit |
| `dose_amount` | `"1"` | Tablets per dose, from "Take 1 tablet…" |
| `schedule_times` | `"08:00"` or `"08:00, 20:00"` | Convert label wording: once daily → `08:00`; twice daily → `08:00, 20:00`; at bedtime → `20:00`; three times → `08:00, 14:00, 20:00`. Lower the confidence when converting |
| `quantity_start` | `"30"` | From "QTY" |
| `refills_remaining` | `"2"`, `"0"` | From "Refills"; "No refills" → `"0"` |
| `pharmacy_name`, `pharmacy_phone` | `"CVS Pharmacy"`, `"(732) 555-0123"` | |
| `prescriber` | `"Dr. Patel"` | |

### Confidence → what the caregiver sees

The backend converts confidence into the `state` the UI shows. Agree on these cutoffs as a team;
these are the suggested defaults:

| Confidence | `state` | What the UI does |
|---|---|---|
| ≥ 0.85 | `filled` | Shown as found (green) |
| 0.50 to 0.85 | `unsure` | Butter highlight, "Hard to read. Please check." |
| < 0.50 or no value | `missing` | Coral highlight, the caregiver must type it (if required) |

### Merging several photos of one bottle

When a new photo arrives for the same scan, keep the **highest-confidence** value for each
field across all photos. Never replace a `filled` value with a lower-confidence one. After
merging, if any required field (`name`, `strength`, `dose_amount`, `schedule_times`,
`quantity_start`) is still missing, the backend moves the scan to `asking_patient`.

### Privacy

Delete the images once the scan is complete or discarded. Store only the extracted text.
Never run face recognition; crop to the label where possible.

## 2. Counting pills (tray scan)

When Rosa pours pills onto the tray, the counter returns:

```json
{ "medication_id": 3, "count": 12, "confidence": 0.94 }
```

The backend applies it like `POST /medications/{id}/counts`. The UI updates the bottle and
tiles on the next poll. Below about 0.8 confidence, ask Rosa to spread the pills out and
recount instead of saving.

## 3. Wearable events

| What happened | Send to the backend | Where the UI shows it |
|---|---|---|
| Rosa took a dose and confirmed | A dose: `medication_id`, `slot`, `taken_at`, `method: "voice"` or `"button"` | Today's doses, bottle level, recent doses, History |
| Wrong bottle picked up | An event: `type: "wrong_bottle"` and a one-sentence `message` | Home → Mistakes caught |
| Same dose twice | An event: `type: "double_dose"` | Home → Mistakes caught |
| Rosa couldn't answer a missing field | Scan `history` step and status `needs_caregiver` | Home → Needs your help, Verify timeline |

Write event messages as plain sentences for the caregiver, e.g. "Rosa picked up Metformin
when Lisinopril was due. MedCheck stopped her before she took it."

## Testing without the UI

Each output above has a matching example in [`fixtures/`](fixtures/). If your pipeline's JSON,
after the backend converts it, matches those files, the UI will display it correctly.
