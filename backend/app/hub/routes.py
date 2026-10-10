"""Endpoints from frontend/docs/api-contract.md. Errors are {"detail": "<sentence>"} as the UI expects."""

import calendar
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, current_app, jsonify, request
from sqlalchemy import delete, select, text
from werkzeug.exceptions import HTTPException

from app.errors import ApiError
from app.extensions import db
from app.hub import contacts, labels, rx
from app.hub.defaults import DEFAULT_SETTINGS
from app.hub.state import (
    build_state,
    doses_today,
    dose_refs,
    find_tracked,
    get_settings,
    hub_patient,
    local_today,
    medication_json,
    scan_json,
    tracked,
)
from app.models import (
    DoseEvent,
    HubAlert,
    HubEvent,
    HubMedication,
    HubReminder,
    HubScan,
    HubSettings,
    RefillRequest,
)
from app.models.hub import EVENT_TYPES, HUB_METHODS
from app.services import doses as dose_service
from app.services import inventory as inv_service
from app.services import notifications
from app.services.normalize import normalize_strength
from app.utils.time import get_zone, utcnow

hub_bp = Blueprint("hub", __name__)

MAX_PHOTO_BYTES = 12 * 1024 * 1024
HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


# ---------- errors ----------


def detail(status: int, message: str):
    return jsonify({"detail": message}), status


@hub_bp.errorhandler(ApiError)
def _api_error(exc: ApiError):
    db.session.rollback()
    return detail(exc.status, exc.message)


@hub_bp.errorhandler(HTTPException)
def _http_error(exc: HTTPException):
    db.session.rollback()
    return detail(exc.code or 500, exc.description or "Request failed.")


@hub_bp.errorhandler(Exception)
def _unexpected(exc: Exception):
    db.session.rollback()
    current_app.logger.exception("hub error")
    return detail(500, "Something went wrong on the MedCheck hub. Please try again.")


def unprocessable(message: str) -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", message)


def body() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def state_response():
    return jsonify(build_state(hub_patient()))


# ---------- health & state ----------


@hub_bp.get("/health")
def health():
    db.session.execute(text("SELECT 1"))
    return jsonify({"ok": True})


@hub_bp.get("/state")
def state():
    return state_response()


# ---------- medications ----------


@hub_bp.post("/medications/<int:med_id>/doses")
def log_dose(med_id: int):
    """Log a dose for today's next untaken slot (or the given slot). method: dashboard | voice | button."""
    patient = hub_patient()
    hm, item = find_tracked(patient, med_id)
    data = body()
    method = data.get("method") or "dashboard"
    if method not in HUB_METHODS:
        raise unprocessable("method must be voice, button or dashboard.")
    slot = data.get("slot")
    tz = get_zone(patient.timezone)
    now = utcnow()
    events = doses_today(patient, item)
    if slot:
        matches = [e for e in events if e.scheduled_at.astimezone(tz).strftime("%H:%M") == slot]
        if not matches:
            raise unprocessable(f"{item.medication.name} isn't scheduled at {slot} today.")
        event = matches[0]
        if event.status in ("taken_on_time", "taken_late"):
            raise ApiError(409, "ALREADY_LOGGED", f"The {slot} dose of {item.medication.name} is already logged.")
    else:
        open_now = [e for e in events if e.status in ("pending", "missed") and e.on_time_start <= now <= e.confirm_deadline]
        if not open_now:
            upcoming = [e for e in events if e.status == "pending" and e.on_time_start > now]
            if upcoming:
                opens = upcoming[0].on_time_start.astimezone(tz).strftime("%H:%M")
                due = upcoming[0].scheduled_at.astimezone(tz).strftime("%H:%M")
                raise ApiError(409, "NOT_DUE", f"The {due} dose of {item.medication.name} can be logged from {opens}.")
            raise ApiError(409, "NOTHING_DUE", f"All of today's {item.medication.name} doses are already logged or closed.")
        event = open_now[0]
    locked = dose_service.lock_event(event.id)
    dose_service.confirm(locked, user_id=patient.id, observation_event_id=None, quantity_taken=None)
    ref = dose_refs([locked.id])[locked.id]
    ref.method = method
    db.session.commit()
    return state_response()


@hub_bp.post("/medications/<int:med_id>/remind")
def remind(med_id: int):
    """Caregiver asks for the reminder to be repeated. Recorded and sent to the patient (in-app / SMS)."""
    patient = hub_patient()
    hm, item = find_tracked(patient, med_id)
    slot = body().get("slot")
    if slot is not None and not HHMM.match(str(slot)):
        raise unprocessable("slot must look like 08:00.")
    settings = get_settings(patient)
    you = next((c for c in settings.get("caregivers") or [] if c.get("you")), None)
    who = (you or {}).get("name") or "Your caregiver"
    label = notifications.med_label(item)
    db.session.add(HubReminder(patient_id=patient.id, hub_medication_id=hm.id, slot=slot, date=local_today(patient), sent_at=utcnow()))
    notifications.create_reminder(
        patient_id=patient.id,
        recipient_id=patient.id,
        kind="dose_followup",
        title=f"Reminder: {label}",
        body=f"{who} is reminding you to take {label}{f' ({slot} dose)' if slot else ''}.",
    )
    db.session.commit()
    return state_response()


def _parse_int(value, name: str, minimum: int = 0, allow_none: bool = False):
    if value is None or value == "":
        if allow_none:
            return None
        raise unprocessable(f"{name} is required.")
    try:
        n = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise unprocessable(f"{name} must be a whole number.")
    if n != n.to_integral_value() or n < minimum:
        raise unprocessable(f"{name} must be a whole number of at least {minimum}.")
    return int(n)


@hub_bp.post("/medications/<int:med_id>/counts")
def record_count(med_id: int):
    """Correct the pill count. Optional confidence (tray counter): below 0.8 asks for a recount."""
    patient = hub_patient()
    hm, item = find_tracked(patient, med_id)
    data = body()
    count = _parse_int(data.get("count"), "count")
    conf = data.get("confidence")
    if conf is not None and float(conf) < 0.8:
        raise unprocessable("The count wasn't clear. Spread the pills out and count again.")
    inv = inv_service.ensure_inventory(patient.id, item.medication_id, item.dose_unit or "tablet")
    inv_service.set_quantity(inv, Decimal(count), created_by=patient.id, note="pill count from dashboard")
    db.session.commit()
    return state_response()


@hub_bp.post("/medications/<int:med_id>/refill")
def mark_refilled(med_id: int):
    """Refill picked up: +quantity_start, refills_remaining -= 1, fill_date = today, clear low_* alerts."""
    patient = hub_patient()
    hm, item = find_tracked(patient, med_id)
    qty = hm.quantity_start or (int(item.quantity_prescribed) if item.quantity_prescribed else None)
    if not qty:
        raise unprocessable("Set how many tablets come in a full bottle before logging a refill.")
    now = utcnow()
    refill = RefillRequest(
        patient_id=patient.id, prescription_item_id=item.id, status="fulfilled", requested_by=patient.id,
        fulfilled_at=now, quantity_added=Decimal(qty),
    )
    db.session.add(refill)
    db.session.flush()
    inv_service.ensure_inventory(patient.id, item.medication_id, item.dose_unit or "tablet")
    inv_service.apply_transaction(
        patient.id, item.medication_id, Decimal(qty), "refill",
        refill_request_id=refill.id, created_by=patient.id, initialize_if_unknown=True,
    )
    if hm.refills_remaining:
        hm.refills_remaining -= 1
    hm.fill_date = local_today(patient)
    db.session.execute(delete(HubAlert).where(HubAlert.hub_medication_id == hm.id, HubAlert.type.like("low_%")))
    db.session.commit()
    return state_response()


_PATCHABLE_TEXT = ("purpose", "prescriber", "prescriber_phone", "pharmacy_name", "pharmacy_phone")


@hub_bp.patch("/medications/<int:med_id>")
def update_medication(med_id: int):
    patient = hub_patient()
    hm, item = find_tracked(patient, med_id)
    data = body()
    for key in _PATCHABLE_TEXT:
        if key in data:
            setattr(hm, key, str(data[key] or "").strip()[:200])
    if "instructions" in data:
        text_value = str(data["instructions"] or "").strip()
        if not text_value:
            raise unprocessable("Instructions can't be empty.")
        item.instructions = text_value[:2000]  # label text; schedule and dose amount are unchanged
    if "quantity_start" in data:
        hm.quantity_start = _parse_int(data["quantity_start"], "Tablets in a full bottle", minimum=1)
    if "refills_remaining" in data:
        hm.refills_remaining = _parse_int(data["refills_remaining"], "Refills", allow_none=True)
        if hm.refills_remaining and hm.refills_remaining > 0:
            db.session.execute(delete(HubAlert).where(HubAlert.hub_medication_id == hm.id, HubAlert.type == "no_refills"))
    hm.confidence = {}
    db.session.commit()
    return state_response()


@hub_bp.delete("/medications/<int:med_id>")
def stop_tracking(med_id: int):
    """Stop tracking: new prescription version without this medication. Dose history is kept."""
    patient = hub_patient()
    hm, item = find_tracked(patient, med_id)
    rx.remove_medication(patient, item.medication_id)
    db.session.commit()
    return state_response()


# ---------- scans ----------


def _scan(scan_id: int) -> HubScan:
    patient = hub_patient()
    scan = db.session.get(HubScan, scan_id)
    if scan is None or scan.patient_id != patient.id:
        raise ApiError(404, "SCAN_NOT_FOUND", "That scan couldn't be found.")
    return scan


def _read_photo(scan: HubScan) -> None:
    """Send the uploaded photo to inference and merge the result into the scan."""
    upload = request.files.get("photo")
    if upload is None:
        raise unprocessable("Attach a photo in the 'photo' field.")
    data = upload.read(MAX_PHOTO_BYTES + 1)
    if not data:
        raise unprocessable("The photo was empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise ApiError(413, "PHOTO_TOO_LARGE", "That photo is too large. Use a photo under 12 MB.")
    content_type = (upload.mimetype or "").lower()
    if content_type not in ("image/jpeg", "image/png"):
        content_type = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    patient = hub_patient()
    known = [
        {"name": item.medication.name, **({"strength": _strength_obj(item.medication.strength)} if item.medication.strength else {})}
        for _, item in tracked(patient)
    ]
    result = labels.read_label(data, content_type, known)
    scan.photos += 1
    fields, confidence = dict(scan.fields), dict(scan.confidence)
    if result.get("status") == "needs_rescan":
        scan.guidance = (result.get("frame_quality") or {}).get("guidance") or ["Hold the bottle steady and try another photo."]
    else:
        labels.merge(fields, confidence, labels.readings_from_inference(result))
        raw = (result.get("instructions") or {}).get("raw_text")
        if raw and not scan.instructions:
            scan.instructions = raw
        scan.guidance = []
    scan.fields, scan.confidence = fields, confidence
    found = sum(1 for f in fields.values() if f["state"] != "missing")
    now = utcnow().isoformat()
    if scan.photos == 1:
        scan.history = [{"step": "Scanned", "at": now, "detail": f"Read {found} of {len(labels.FIELD_ORDER)} details."}]
    missing = labels.missing_required(fields)
    if missing and scan.status == "reading" and scan.photos >= 2:
        scan.status = "asking_patient"
        scan.history = [
            *scan.history,
            {"step": "Still missing", "at": now, "detail": "Couldn't read: " + ", ".join(labels.LABELS[k] for k in missing) + "."},
        ]
    elif not missing and scan.status == "asking_patient":
        scan.status = "reading"


def _strength_obj(strength: str) -> dict:
    parts = strength.split(" ", 1)
    try:
        return {"value": float(parts[0]), "unit": parts[1] if len(parts) > 1 else None}
    except ValueError:
        return {}


@hub_bp.post("/scans")
def start_scan():
    patient = hub_patient()
    if request.is_json and body().get("manual"):
        scan = HubScan(patient_id=patient.id, status="reading", photos=0, manual=True, fields=labels.empty_fields(), confidence={}, history=[], guidance=[])
        db.session.add(scan)
        db.session.commit()
        return jsonify(scan_json(scan))
    scan = HubScan(patient_id=patient.id, status="reading", photos=0, manual=False, fields=labels.empty_fields(), confidence={}, history=[], guidance=[])
    db.session.add(scan)
    db.session.flush()
    _read_photo(scan)
    db.session.commit()
    return jsonify(scan_json(scan))


@hub_bp.post("/scans/<int:scan_id>/photos")
def add_photo(scan_id: int):
    scan = _scan(scan_id)
    if scan.status == "complete":
        raise ApiError(409, "SCAN_COMPLETE", "This medication was already added.")
    _read_photo(scan)
    db.session.commit()
    return jsonify(scan_json(scan))


@hub_bp.get("/scans/<int:scan_id>")
def get_scan(scan_id: int):
    return jsonify(scan_json(_scan(scan_id)))


@hub_bp.delete("/scans/<int:scan_id>")
def discard_scan(scan_id: int):
    db.session.delete(_scan(scan_id))
    db.session.commit()
    return state_response()


def _times(raw: str) -> list[str]:
    out = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        m = HHMM.match(part)
        if not m:
            raise unprocessable(f"“{part}” isn't a time. Use 24-hour times like 08:00, 20:00.")
        t = f"{int(m.group(1)):02d}:{m.group(2)}"
        if t not in out:
            out.append(t)
    if not out:
        raise unprocessable("Add at least one time of day, like 08:00.")
    return sorted(out)


@hub_bp.post("/scans/<int:scan_id>/complete")
def complete_scan(scan_id: int):
    """Add the medication: new prescription version, schedule, stock = quantity_start, doses generated."""
    scan = _scan(scan_id)
    if scan.status == "complete":
        raise ApiError(409, "SCAN_COMPLETE", "This medication was already added.")
    patient = hub_patient()
    v = {k: str(val).strip() for k, val in body().items() if val is not None}
    if not v.get("name"):
        raise unprocessable("Add the medication name.")
    strength = normalize_strength(v.get("strength"))
    if not strength:
        raise unprocessable("Add the strength, like 25 mg.")
    dose_amount = _parse_int(v.get("dose_amount"), "Tablets per dose", minimum=1)
    times = _times(v.get("schedule_times"))
    quantity_start = _parse_int(v.get("quantity_start"), "Tablets in the bottle", minimum=1)
    refills = _parse_int(v.get("refills_remaining"), "Refills", allow_none=True)
    when = ", ".join(times)
    instructions = scan.instructions or f"Take {dose_amount} tablet{'s' if dose_amount != 1 else ''} at {when}."
    result = rx.add_medication(
        patient,
        {
            "name": v["name"], "strength": strength, "dosage_form": "tablet",
            "dose_quantity": Decimal(dose_amount), "dose_unit": "tablet",
            "quantity_prescribed": Decimal(quantity_start), "refills_authorized": refills,
            "instructions": instructions,
        },
        times,
    )
    hm = db.session.scalar(
        select(HubMedication).where(HubMedication.patient_id == patient.id, HubMedication.medication_id == result["item_medication_id"])
    )
    if hm is None:
        hm = HubMedication(patient_id=patient.id, medication_id=result["item_medication_id"])
        db.session.add(hm)
    # Fields the caregiver left exactly as an "unsure" reading stay marked unsure.
    unsure = {
        k: "unsure" for k, f in scan.fields.items()
        if f.get("state") == "unsure" and f.get("value") == v.get(k, "") and k in ("prescriber", "pharmacy_name", "pharmacy_phone", "refills_remaining")
    }
    hm.quantity_start, hm.refills_remaining = quantity_start, refills
    hm.prescriber, hm.pharmacy_name, hm.pharmacy_phone = v.get("prescriber", ""), v.get("pharmacy_name", ""), v.get("pharmacy_phone", "")
    hm.fill_date, hm.confidence, hm.otc = local_today(patient), unsure, False
    hm.purpose = hm.purpose or ""
    hm.prescriber_phone = hm.prescriber_phone or ""
    db.session.flush()
    scan.status = "complete"
    scan.medication_id = hm.id
    scan.history = [*scan.history, {"step": "Added", "at": utcnow().isoformat(), "detail": f"{v['name']} {strength} is now tracked."}]
    db.session.commit()
    hm, item = find_tracked(patient, hm.id)
    med = medication_json(patient, hm, item)
    build_state(patient)  # runs supply checks for the new bottle
    return jsonify({"medication": med, "warnings": result.get("warnings", [])})


# ---------- adherence ----------


@hub_bp.get("/adherence")
def adherence():
    """Month calendar. Counts only slots whose time has passed; skipped doses are not due."""
    patient = hub_patient()
    m = re.match(r"^(\d{4})-(\d{2})$", request.args.get("month", ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise unprocessable("month must look like 2026-10.")
    year, month = int(m.group(1)), int(m.group(2))
    tz = get_zone(patient.timezone)
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    now = utcnow()
    today = local_today(patient)
    hub_ids = {hm.medication_id: hm.id for hm in db.session.scalars(select(HubMedication).where(HubMedication.patient_id == patient.id))}
    events = db.session.scalars(
        select(DoseEvent)
        .where(DoseEvent.patient_id == patient.id, DoseEvent.scheduled_at >= start, DoseEvent.scheduled_at < end, DoseEvent.scheduled_at <= now)
        .order_by(DoseEvent.scheduled_at)
    ).all()
    by_day: dict[date, list[DoseEvent]] = {}
    for e in events:
        if e.status == "skipped":
            continue
        by_day.setdefault(e.scheduled_at.astimezone(tz).date(), []).append(e)
    days = []
    for d in range(1, calendar.monthrange(year, month)[1] + 1):
        day = date(year, month, d)
        future = day > today
        evs = [] if future else by_day.get(day, [])
        missed = [
            e for e in evs
            if e.status == "missed" or (e.status == "pending" and now > e.on_time_end)
        ]
        days.append({
            "date": day.isoformat(),
            "due": len(evs),
            "missed": len(missed),
            "future": future,
            "missedList": [
                {"medication_id": hub_ids.get(e.medication_id), "name": e.medication.name,
                 "slot": e.scheduled_at.astimezone(tz).strftime("%H:%M")}
                for e in missed
            ],
        })
    due = sum(x["due"] for x in days)
    missed_total = sum(x["missed"] for x in days)
    return jsonify({"year": year, "month": month - 1, "due": due, "taken": due - missed_total, "missed": missed_total, "days": days})


# ---------- settings & data ----------


def _clean_settings(raw: dict) -> dict:
    t = raw.get("thresholds") or {}
    try:
        thresholds = {k: int(t[k]) for k in ("first", "second", "urgent")}
    except (KeyError, TypeError, ValueError):
        raise unprocessable("Thresholds need whole numbers for first, second and urgent.")
    if not thresholds["first"] >= thresholds["second"] >= thresholds["urgent"] >= 0:
        raise unprocessable("Thresholds must go from most days to fewest: first ≥ second ≥ urgent.")
    remind = str(raw.get("remind_again", "30"))
    if remind not in ("30", "60", "never"):
        raise unprocessable("Remind again must be 30, 60 or never.")
    caregivers, next_id = [], max([c.get("id", 0) for c in raw.get("caregivers") or [] if isinstance(c.get("id"), int)] + [0]) + 1
    for c in raw.get("caregivers") or []:
        name = str(c.get("name", "")).strip()
        if not name:
            raise unprocessable("Every caregiver needs a name.")
        phone = str(c.get("phone", "")).strip()
        if phone and contacts.to_e164(phone) is None:
            raise unprocessable(f"{name}'s phone number doesn't look right.")
        scope = c.get("scope", "all")
        if scope not in ("all", "refills"):
            raise unprocessable("Caregiver scope must be all or refills.")
        cid = c.get("id") if isinstance(c.get("id"), int) else None
        if cid is None:
            cid, next_id = next_id, next_id + 1
        entry = {"id": cid, "name": name[:100], "phone": phone[:40], "scope": scope}
        if c.get("you"):
            entry["you"] = True
        caregivers.append(entry)
    return {
        **DEFAULT_SETTINGS,
        "thresholds": thresholds,
        "alert_missed": bool(raw.get("alert_missed", True)),
        "alert_no_refills": bool(raw.get("alert_no_refills", True)),
        "alert_wrong_bottle": bool(raw.get("alert_wrong_bottle", False)),
        "remind_again": remind,
        "voice_language": str(raw.get("voice_language", "English"))[:40],
        "camera_paused": bool(raw.get("camera_paused", False)),
        "caregivers": caregivers,
    }


@hub_bp.put("/settings")
def save_settings():
    patient = hub_patient()
    get_settings(patient)
    row = db.session.get(HubSettings, patient.id)
    row.settings = _clean_settings(body())
    db.session.commit()
    return state_response()


@hub_bp.get("/export")
def export_data():
    patient = hub_patient()
    data = build_state(patient)
    payload = current_app.json.dumps({"exported_at": utcnow(), "state": data}, indent=2)
    return Response(
        payload,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="medcheck-export-{local_today(patient).isoformat()}.json"'},
    )


@hub_bp.delete("/data")
def delete_all():
    """Delete the patient's medications, doses, stock, scans, alerts and events. Settings and caregivers stay."""
    patient = hub_patient()
    pid = {"p": patient.id}
    for sql in (
        "DELETE FROM hub_alerts WHERE patient_id = :p",
        "DELETE FROM hub_reminders WHERE patient_id = :p",
        "DELETE FROM hub_scans WHERE patient_id = :p",
        "DELETE FROM hub_events WHERE patient_id = :p",
        "DELETE FROM reminders WHERE patient_id = :p",
        "DELETE FROM refill_requests WHERE patient_id = :p",
        "DELETE FROM medication_inventory WHERE patient_id = :p",
        "DELETE FROM dose_outcomes WHERE patient_id = :p",
        "DELETE FROM vision_observations WHERE patient_id = :p",
        "DELETE FROM prescriptions WHERE patient_id = :p",
        "DELETE FROM hub_medications WHERE patient_id = :p",
    ):
        db.session.execute(text(sql), pid)
    db.session.commit()
    return state_response()


# ---------- wearable / inference inputs (not called by the dashboard) ----------


@hub_bp.post("/events")
def add_event():
    """Wearable mistake: {"type": "wrong_bottle"|"double_dose", "message": "...", "at"?: ISO}."""
    patient = hub_patient()
    data = body()
    if data.get("type") not in EVENT_TYPES:
        raise unprocessable("type must be wrong_bottle or double_dose.")
    message = str(data.get("message", "")).strip()
    if not message:
        raise unprocessable("message is required.")
    at = utcnow()
    if data.get("at"):
        try:
            at = datetime.fromisoformat(str(data["at"]).replace("Z", "+00:00"))
        except ValueError:
            raise unprocessable("at must be an ISO 8601 time.")
        if at.tzinfo is None:
            raise unprocessable("at needs a timezone, e.g. 2026-10-10T18:30:00Z.")
    db.session.add(HubEvent(patient_id=patient.id, type=data["type"], message=message[:500], at=at))
    settings = get_settings(patient)
    if settings.get("alert_wrong_bottle"):
        contacts.text_contacts(settings, f"MedCheck: {message}")
    db.session.commit()
    return state_response()


def on_missed(event: DoseEvent) -> None:
    """Worker hook: text the dashboard contacts about a missed dose when alert_missed is on."""
    settings_row = db.session.get(HubSettings, event.patient_id)
    if settings_row is None or not settings_row.settings.get("alert_missed", True):
        return
    from app.models import User

    patient = db.session.get(User, event.patient_id)
    at = event.scheduled_at.astimezone(get_zone(patient.timezone)).strftime("%H:%M")
    label = notifications.med_label(event.item)
    contacts.text_contacts(settings_row.settings, f"MedCheck: {patient.name.split()[0]} hasn't taken the {at} dose of {label}.")
