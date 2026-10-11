"""Label photo -> inference service -> the dashboard's nine scan fields.

Mapping (frontend/docs/inference-contract.md):
  name, strength, dose_amount   <- inference medication/instructions fields (their confidence)
  schedule_times, quantity_start, refills_remaining, pharmacy_name, pharmacy_phone, prescriber
                                <- inference v1.3 `label_meta` (their confidence) when present;
                                   otherwise fallback: schedule converted from frequency wording
                                   (confidence capped at 0.7) and regex over the raw OCR label
                                   text (0.7-0.75, so the caregiver is asked to check).
                                   Nothing is filled unless it is literally present on the label.
Confidence -> state: >= 0.85 filled, >= 0.50 unsure, otherwise missing (value cleared).
"""

import json
import re

import requests
from flask import current_app

from app.errors import ApiError
from app.services.normalize import normalize_strength
from app.utils import http

FIELD_ORDER = (
    "name", "strength", "dose_amount", "schedule_times", "quantity_start",
    "refills_remaining", "pharmacy_name", "pharmacy_phone", "prescriber",
)
REQUIRED = ("name", "strength", "dose_amount", "schedule_times", "quantity_start")
LABELS = {
    "name": "medication name", "strength": "strength", "dose_amount": "amount per dose",
    "schedule_times": "times of day", "quantity_start": "amount in the bottle",
    "refills_remaining": "refills", "pharmacy_name": "pharmacy", "pharmacy_phone": "pharmacy phone",
    "prescriber": "prescriber",
}
FILLED, UNSURE = 0.85, 0.50
CONVERTED_CAP = 0.70   # schedule converted from wording ("twice daily")
TEXT_PARSED = 0.75     # parsed by regex from raw OCR text
PHONE_PARSED = 0.70

_FREQUENCIES = [
    (re.compile(r"\b(four times|4 times|qid)\b", re.I), "08:00, 12:00, 16:00, 20:00"),
    (re.compile(r"\b(three times|3 times|tid)\b", re.I), "08:00, 14:00, 20:00"),
    (re.compile(r"\b(twice|two times|2 times|bid)\b", re.I), "08:00, 20:00"),
    (re.compile(r"\b(at bedtime|bedtime|at night|nightly)\b", re.I), "20:00"),
    (re.compile(r"\b(once|daily|every day|each day|every morning|in the morning|qd)\b", re.I), "08:00"),
]

# Interval cadences are NOT day-anchored: the first dose time decides every later clock time,
# so converting "every 8 hours" into 08:00/14:00/20:00 invents a non-equivalent schedule.
# When this matches, no schedule is inferred and the caregiver must set the times explicitly.
_INTERVAL = re.compile(
    r"\bevery\s*(?:\d+|other)\s*(?:hours?|hrs?|days?|weeks?)\b|\bevery\s*other\s*day\b|\bq\s?\d+\s*h\b",
    re.I,
)
_QTY = re.compile(r"\b(?:QTY|QUANTITY)\s*[:#]?\s*(\d{1,4})\b", re.I)
_REFILLS = re.compile(r"\bREFILLS?\s*(?:REMAINING|LEFT)?\s*[:#]?\s*(\d{1,2})\b", re.I)
_NO_REFILLS = re.compile(r"\bNO\s+REFILLS\b", re.I)
_PHONE = re.compile(r"\(?\b(\d{3})\)?[\s.\-]?(\d{3})[\s.\-](\d{4})\b")
_DOCTOR = re.compile(r"\b(?:DR\.?|PRESCRIBER\s*[:#]?\s*(?:DR\.?)?)\s+([A-Z][A-Za-z'\-]+(?:\s[A-Z][A-Za-z'\-]+)?)", re.I)
_PHARMACIES = {
    "cvs": "CVS Pharmacy", "walgreens": "Walgreens", "rite aid": "Rite Aid", "walmart": "Walmart Pharmacy",
    "costco": "Costco Pharmacy", "kroger": "Kroger Pharmacy", "target": "Target Pharmacy",
    "wegmans": "Wegmans Pharmacy", "shoprite": "ShopRite Pharmacy", "publix": "Publix Pharmacy",
}


def empty_fields() -> dict:
    return {k: {"value": "", "state": "missing"} for k in FIELD_ORDER}


def state_for(confidence: float, value: str) -> str:
    if not value or confidence < UNSURE:
        return "missing"
    return "filled" if confidence >= FILLED else "unsure"


def form_from_inference(scan: dict) -> tuple[str | None, str | None]:
    """Dosage form and dose unit as read by inference (never invented).

    A field only counts when it carries a usable source and confidence — the VLM can
    return ``"tablet"`` with confidence 0 for a label that never states a form, and that
    guess must not become the medication's dosage form. Returns (None, None) when the
    evidence is missing or too weak so the caller can ask for review instead.
    """
    med = scan.get("medication") or {}
    form_field = med.get("form") or {}
    form = str(form_field.get("value")).strip().lower() if form_field.get("value") else None
    form_source = str(form_field.get("source") or "none")
    form_conf = float(form_field.get("confidence") or 0)
    if form in ("", "none") or form_source == "none" or form_conf < UNSURE:
        form = None

    dose = (scan.get("instructions") or {}).get("dose") or {}
    unit = str(dose.get("unit")).strip().lower() if dose.get("unit") else None
    unit_source = str(dose.get("source") or "none")
    unit_conf = float(dose.get("confidence") or 0)
    if unit in ("", "none") or unit_source == "none" or unit_conf < UNSURE:
        unit = None
    return form, unit


def form_noun(form: str | None, unit: str | None = None) -> str:
    """Counting noun for copy: tablet / capsule / unit (never silently 'tablet')."""
    for candidate in (form, unit):
        if candidate in ("tablet", "tablets"):
            return "tablet"
        if candidate in ("capsule", "capsules"):
            return "capsule"
    return "unit"


def form_plural(noun: str) -> str:
    return "tablets" if noun == "tablet" else "capsules" if noun == "capsule" else "units"


def _num(v) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v) == int(v) else str(v)


def readings_from_inference(scan: dict) -> dict[str, tuple[str, float]]:
    """Inference ScanResponse -> {field: (value, confidence)} for fields it supports."""
    out: dict[str, tuple[str, float]] = {}
    med = scan.get("medication") or {}
    name = med.get("name") or {}
    if name.get("value"):
        out["name"] = (str(name["value"]).strip(), float(name.get("confidence") or 0))
    strength = med.get("strength") or {}
    if strength.get("value") is not None:
        text = normalize_strength({"value": strength["value"], "unit": strength.get("unit")})
        if text:
            out["strength"] = (text, float(strength.get("confidence") or 0))

    instructions = scan.get("instructions") or {}
    dose = instructions.get("dose") or {}
    if dose.get("quantity") is not None and dose.get("source") != "none":
        out["dose_amount"] = (_num(dose["quantity"]), float(dose.get("confidence") or 0))

    wording = " ".join(
        [p.get("text", "") for p in instructions.get("parsed") or [] if p.get("kind") == "frequency"]
        + [instructions.get("raw_text") or ""]
    )
    if not _INTERVAL.search(wording):
        for pattern, times in _FREQUENCIES:
            if pattern.search(wording):
                base = float(dose.get("confidence") or (scan.get("label") or {}).get("confidence") or 0.6)
                out["schedule_times"] = (times, min(base, CONVERTED_CAP))
                break

    # v1.3: inference reads label metadata itself. Prefer it; regexes below only fill gaps
    # (older gateways, or fields label_meta left empty).
    meta = scan.get("label_meta") or {}
    meta_out: dict[str, tuple[str, float]] = {}
    for key in ("schedule_times", "quantity_start", "refills_remaining", "pharmacy_name", "pharmacy_phone", "prescriber"):
        f = meta.get(key) or {}
        if f.get("value") not in (None, "") and f.get("source") != "none":
            meta_out[key] = (str(f["value"]).strip(), float(f.get("confidence") or 0))

    text = (scan.get("label") or {}).get("text") or ""
    out.update(_regex_fields(text, skip=meta_out.keys()))
    out.update(meta_out)
    return out


def _regex_fields(text: str, skip) -> dict[str, tuple[str, float]]:
    out: dict[str, tuple[str, float]] = {}
    if m := _QTY.search(text):
        out["quantity_start"] = (str(int(m.group(1))), TEXT_PARSED)
    if _NO_REFILLS.search(text):
        out["refills_remaining"] = ("0", TEXT_PARSED)
    elif m := _REFILLS.search(text):
        out["refills_remaining"] = (str(int(m.group(1))), TEXT_PARSED)
    if m := _PHONE.search(text):
        out["pharmacy_phone"] = (f"({m.group(1)}) {m.group(2)}-{m.group(3)}", PHONE_PARSED)
    lowered = text.lower()
    for key, display in _PHARMACIES.items():
        if key in lowered:
            out["pharmacy_name"] = (display, TEXT_PARSED)
            break
    if m := _DOCTOR.search(text):
        out["prescriber"] = (f"Dr. {m.group(1).strip().title()}", PHONE_PARSED)
    return {k: v for k, v in out.items() if k not in skip}


def merge(fields: dict, confidence: dict, readings: dict[str, tuple[str, float]]) -> int:
    """Keep the highest-confidence value per field. Returns how many fields improved."""
    improved = 0
    for key, (value, conf) in readings.items():
        if key not in FIELD_ORDER or not value:
            continue
        if conf > float(confidence.get(key, 0)):
            confidence[key] = round(conf, 3)
            state = state_for(conf, value)
            fields[key] = {"value": value if state != "missing" else "", "state": state}
            improved += 1
    return improved


def missing_required(fields: dict) -> list[str]:
    return [k for k in REQUIRED if fields.get(k, {}).get("state") == "missing"]


def read_label(image: bytes, content_type: str, known: list[dict]) -> dict:
    """Call the inference gateway. Raises ApiError with a caregiver-readable message on failure."""
    cfg = current_app.config
    headers = {"Authorization": f"Bearer {cfg['HUB_INFERENCE_API_KEY']}"} if cfg.get("HUB_INFERENCE_API_KEY") else {}
    data = {"client": "backend", "mode": "auto"}
    if known:
        data["hints"] = json.dumps({"known_candidates": known, "locale": "en-US"})
    try:
        resp = http.post(
            f"{cfg['HUB_INFERENCE_URL']}/v1/scan",
            files={"image": ("label", image, content_type)},
            data=data,
            headers=headers,
            timeout=cfg["HUB_INFERENCE_TIMEOUT_S"],
        )
    except requests.RequestException as exc:
        current_app.logger.warning("Inference unreachable: %s", exc)
        raise ApiError(503, "INFERENCE_UNAVAILABLE", "The label reader isn't reachable right now. Try again in a minute, or enter the details by hand.")
    if resp.status_code == 413:
        raise ApiError(413, "PHOTO_TOO_LARGE", "That photo is too large. Use a photo under 12 MB.")
    if resp.status_code == 415:
        raise ApiError(415, "PHOTO_TYPE", "Use a JPEG or PNG photo.")
    if resp.status_code != 200:
        current_app.logger.warning("Inference HTTP %s: %s", resp.status_code, resp.text[:300])
        raise ApiError(502, "INFERENCE_ERROR", "The label reader had a problem with that photo. Try another photo.")
    body = resp.json()
    if body.get("status") == "error":
        raise ApiError(502, "INFERENCE_ERROR", "The label reader couldn't process that photo. Try another photo.")
    return body
