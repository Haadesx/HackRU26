"""Builds the dashboard's GET /state from the core tables (plus the hub_* tables)."""

import math
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from app.errors import ApiError
from app.extensions import db
from app.hub import contacts
from app.hub.defaults import DEFAULT_SETTINGS
from app.json import to_number
from app.models import (
    CaregiverLink,
    DoseEvent,
    DoseSchedule,
    HubAlert,
    HubDoseRef,
    HubEvent,
    HubMedication,
    HubReminder,
    HubScan,
    HubSettings,
    Prescription,
    PrescriptionItem,
    User,
)
from app.services import inventory as inv_service
from app.utils.time import get_zone, utcnow

TAKEN = ("taken_on_time", "taken_late")
DOSE_HISTORY_DAYS = 31


# ---------- patient & settings ----------


def hub_patient() -> User:
    email = current_app.config["HUB_PATIENT_EMAIL"].lower()
    patient = db.session.scalar(select(User).where(func.lower(User.email) == email, User.role == "patient"))
    if patient is None:
        raise ApiError(
            503,
            "HUB_PATIENT_MISSING",
            "The hub has no patient yet. Run `python -m scripts.seed` in backend/ or set HUB_PATIENT_EMAIL.",
        )
    return patient


def get_settings(patient: User) -> dict:
    row = db.session.get(HubSettings, patient.id)
    if row is None:
        settings = {**DEFAULT_SETTINGS, "caregivers": _default_contacts(patient)}
        db.session.execute(insert(HubSettings).values(patient_id=patient.id, settings=settings, updated_at=utcnow()).on_conflict_do_nothing())
        db.session.flush()
        row = db.session.get(HubSettings, patient.id)
    return row.settings


def _default_contacts(patient: User) -> list[dict]:
    links = db.session.scalars(
        select(CaregiverLink).where(CaregiverLink.patient_id == patient.id, CaregiverLink.status == "active")
    ).all()
    out = []
    for i, link in enumerate(links, start=1):
        c = link.caregiver
        out.append({"id": i, "name": c.name, "phone": c.phone or "", "scope": "all", **({"you": True} if i == 1 else {})})
    return out


# ---------- medications ----------


def local_today(patient: User) -> date:
    return utcnow().astimezone(get_zone(patient.timezone)).date()


def active_items(patient: User) -> list[PrescriptionItem]:
    return list(
        db.session.scalars(
            select(PrescriptionItem)
            .join(Prescription)
            .where(Prescription.patient_id == patient.id, Prescription.status == "active")
            .options(
                selectinload(PrescriptionItem.medication),
                selectinload(PrescriptionItem.schedule).selectinload(DoseSchedule.times),
                selectinload(PrescriptionItem.prescription),
            )
            .order_by(PrescriptionItem.created_at)
        )
    )


def hub_med_for(patient: User, item: PrescriptionItem) -> HubMedication:
    row = db.session.scalar(
        select(HubMedication).where(HubMedication.patient_id == patient.id, HubMedication.medication_id == item.medication_id)
    )
    if row is None:
        tz = get_zone(patient.timezone)
        effective = item.prescription.effective_at or utcnow()
        db.session.execute(
            insert(HubMedication)
            .values(
                patient_id=patient.id,
                medication_id=item.medication_id,
                purpose="",
                quantity_start=int(item.quantity_prescribed) if item.quantity_prescribed else None,
                refills_remaining=item.refills_authorized,
                otc=False,
                fill_date=effective.astimezone(tz).date(),
                prescriber="",
                prescriber_phone="",
                pharmacy_name="",
                pharmacy_phone="",
                confidence={},
                created_at=utcnow(),
            )
            .on_conflict_do_nothing()
        )
        row = db.session.scalar(
            select(HubMedication).where(HubMedication.patient_id == patient.id, HubMedication.medication_id == item.medication_id)
        )
    return row


def tracked(patient: User) -> list[tuple[HubMedication, PrescriptionItem]]:
    return [(hub_med_for(patient, item), item) for item in active_items(patient)]


def find_tracked(patient: User, hub_med_id: int) -> tuple[HubMedication, PrescriptionItem]:
    for hm, item in tracked(patient):
        if hm.id == hub_med_id:
            return hm, item
    raise ApiError(404, "MEDICATION_NOT_FOUND", "That medication no longer exists.")


def schedule_times(item: PrescriptionItem) -> list[str]:
    if item.schedule is None:
        return []
    return [t.local_time.strftime("%H:%M") for t in item.schedule.times]


def _int_or_number(value: Decimal | None):
    return None if value is None else to_number(value)


def medication_json(patient: User, hm: HubMedication, item: PrescriptionItem) -> dict:
    inv = inv_service.get_inventory(patient.id, item.medication_id)
    times = schedule_times(item)
    data = {
        "id": hm.id,
        "name": item.medication.name,
        "strength": item.medication.strength or "",
        "purpose": hm.purpose or "",
        "dose_amount": _int_or_number(item.dose_quantity) or 1,
        "dosage_form": item.medication.dosage_form or "",  # "" = unknown, never assumed
        "dose_unit": item.dose_unit or "",
        "doses_per_day": len(times),
        "schedule_times": times,
        "quantity_start": hm.quantity_start or (int(item.quantity_prescribed) if item.quantity_prescribed else 0),
        # null = stock never recorded (unknown is not zero). Record a count to start tracking.
        "pills_left": _int_or_number(inv.quantity_remaining) if inv else None,
        "refills_remaining": None if hm.otc else hm.refills_remaining,
        "fill_date": hm.fill_date.isoformat() if hm.fill_date else None,
        "instructions": item.instructions or "",
        "prescriber": hm.prescriber,
        "prescriber_phone": hm.prescriber_phone,
        "pharmacy_name": hm.pharmacy_name,
        "pharmacy_phone": hm.pharmacy_phone,
        "confidence": hm.confidence or {},
        # Extras the UI ignores but other clients may use:
        "medication_uuid": str(item.medication_id),
        "prescription_item_id": str(item.id),
    }
    if hm.otc:
        data["otc"] = True
    return data


# ---------- doses ----------


def dose_refs(event_ids: list[uuid.UUID]) -> dict[uuid.UUID, HubDoseRef]:
    if event_ids:
        db.session.execute(
            insert(HubDoseRef).values([{"dose_event_id": e} for e in event_ids]).on_conflict_do_nothing()
        )
    rows = db.session.scalars(select(HubDoseRef).where(HubDoseRef.dose_event_id.in_(event_ids))).all() if event_ids else []
    return {r.dose_event_id: r for r in rows}


def doses_json(patient: User, med_ids: dict[uuid.UUID, int]) -> list[dict]:
    tz = get_zone(patient.timezone)
    since = utcnow() - timedelta(days=DOSE_HISTORY_DAYS)
    events = db.session.scalars(
        select(DoseEvent)
        .where(DoseEvent.patient_id == patient.id, DoseEvent.status.in_(TAKEN), DoseEvent.scheduled_at >= since)
        .order_by(DoseEvent.scheduled_at)
    ).all()
    refs = dose_refs([e.id for e in events])
    out = []
    for e in events:
        if e.medication_id not in med_ids:
            continue
        local = e.scheduled_at.astimezone(tz)
        out.append(
            {
                "id": refs[e.id].id,
                "medication_id": med_ids[e.medication_id],
                "slot": local.strftime("%H:%M"),
                "date": local.date().isoformat(),
                "taken_at": e.taken_at,
                "method": refs[e.id].method or ("button" if e.confirmation_method == "scan" else "dashboard"),
            }
        )
    return out


# ---------- supply alerts (mirrors frontend/src/lib/inventory.js) ----------


def days_left(med: dict) -> float:
    per_day = (med["dose_amount"] or 0) * (med["doses_per_day"] or 0)
    if per_day <= 0:
        return math.inf
    return max(0, med["pills_left"] or 0) / per_day


def check_supply(patient: User, settings: dict, med: dict) -> None:
    """Create each threshold alert once per bottle and text the contacts. Skips unknown stock."""
    t = settings.get("thresholds") or DEFAULT_SETTINGS["thresholds"]
    name = patient.name.split()[0]

    def push(kind: str, message: str):
        new_id = db.session.execute(
            insert(HubAlert)
            .values(patient_id=patient.id, hub_medication_id=med["id"], type=kind, message=message, sent_at=utcnow())
            .on_conflict_do_nothing()
            .returning(HubAlert.id)
        ).scalar()
        if new_id is not None:
            contacts.text_contacts(settings, f"MedCheck: {message}", scopes=("all", "refills"))

    if med.get("refills_remaining") == 0 and settings.get("alert_no_refills", True):
        push("no_refills", f"No refills left for {med['name']}. {med['prescriber'] or 'The doctor'} needs to send a new prescription.")
    if med["pills_left"] is None:
        return
    d = days_left(med)
    for kind, limit in (("low_3", t["urgent"]), ("low_5", t["second"]), ("low_7", t["first"])):
        if d <= limit:
            left = math.floor(d)
            push(kind, f"{name} is out of {med['name']}." if left <= 0 else f"{name} has about {left} days of {med['name']} left.")
            break


# ---------- scans ----------


def escalate_scans(patient: User) -> None:
    """asking_patient for longer than HUB_ASK_PATIENT_MINUTES -> needs_caregiver (contract step 3)."""
    cutoff = utcnow() - timedelta(minutes=current_app.config["HUB_ASK_PATIENT_MINUTES"])
    for scan in db.session.scalars(
        select(HubScan).where(HubScan.patient_id == patient.id, HubScan.status == "asking_patient", HubScan.updated_at < cutoff)
    ):
        scan.status = "needs_caregiver"
        scan.history = [*scan.history, {"step": "Sent to you", "at": utcnow().isoformat(), "detail": "Waiting for you now."}]


def scan_json(scan: HubScan) -> dict:
    data = {
        "id": scan.id,
        "status": scan.status,
        "photos": scan.photos,
        "fields": scan.fields,
        "created_at": scan.created_at,
        "history": scan.history,
    }
    if scan.manual:
        data["manual"] = True
    if scan.medication_id:
        data["medication_id"] = scan.medication_id
    if scan.guidance:
        data["guidance"] = scan.guidance  # extra: camera tips from the last photo
    if scan.dosage_form:
        data["dosage_form"] = scan.dosage_form  # extra: evidence-floored, may be absent
    if scan.dose_unit:
        data["dose_unit"] = scan.dose_unit  # extra: as read by inference
    return data


# ---------- state ----------


def build_state(patient: User) -> dict:
    settings = get_settings(patient)
    escalate_scans(patient)
    pairs = tracked(patient)
    meds = [medication_json(patient, hm, item) for hm, item in pairs]
    for m in meds:
        check_supply(patient, settings, m)
    all_hub_meds = db.session.scalars(select(HubMedication).where(HubMedication.patient_id == patient.id)).all()
    med_ids = {hm.medication_id: hm.id for hm in all_hub_meds}
    today = local_today(patient)
    reminders = db.session.scalars(
        select(HubReminder).where(HubReminder.patient_id == patient.id, HubReminder.date == today).order_by(HubReminder.sent_at)
    ).all()
    alerts = db.session.scalars(
        select(HubAlert).where(HubAlert.patient_id == patient.id).order_by(HubAlert.sent_at.desc())
    ).all()
    events = db.session.scalars(
        select(HubEvent).where(HubEvent.patient_id == patient.id).order_by(HubEvent.at.desc()).limit(50)
    ).all()
    scans = db.session.scalars(
        select(HubScan)
        .where(HubScan.patient_id == patient.id, HubScan.created_at >= utcnow() - timedelta(days=7))
        .order_by(HubScan.created_at)
    ).all()
    contacts_list = settings.get("caregivers") or []
    you = next((c for c in contacts_list if c.get("you")), contacts_list[0] if contacts_list else None)
    state = {
        "now": utcnow(),
        "patient": {"name": patient.name.split()[0], "caregiver": (you or {}).get("name", "").split(" ")[0] if you else ""},
        "hub": {"connected": True},
        "medications": meds,
        "doses": doses_json(patient, med_ids),
        "reminders": [
            {"medication_id": r.hub_medication_id, "slot": r.slot, "date": r.date.isoformat(), "sent_at": r.sent_at}
            for r in reminders
        ],
        "skips": skips_json(patient, med_ids),
        "alerts": [
            {"id": a.id, "medication_id": a.hub_medication_id, "type": a.type, "message": a.message, "sent_at": a.sent_at}
            for a in alerts
        ],
        "events": [{"id": e.id, "type": e.type, "message": e.message, "at": e.at} for e in events],
        "scans": [scan_json(s) for s in scans],
        "settings": settings,
    }
    db.session.commit()
    return state


def skips_json(patient: User, med_ids: dict[uuid.UUID, int]) -> list[dict]:
    """Today's intentionally skipped doses: [{medication_id, slot, at}] (dashboard contract "Skip")."""
    tz = get_zone(patient.timezone)
    start = datetime.combine(local_today(patient), datetime.min.time(), tzinfo=tz)
    events = db.session.scalars(
        select(DoseEvent)
        .where(
            DoseEvent.patient_id == patient.id,
            DoseEvent.status == "skipped",
            DoseEvent.scheduled_at >= start,
            DoseEvent.scheduled_at < start + timedelta(days=1),
        )
        .order_by(DoseEvent.scheduled_at)
    ).all()
    return [
        {
            "medication_id": med_ids[e.medication_id],
            "slot": e.scheduled_at.astimezone(tz).strftime("%H:%M"),
            "at": e.confirmed_at or e.scheduled_at,
        }
        for e in events
        if e.medication_id in med_ids
    ]


def doses_today(patient: User, item: PrescriptionItem) -> list[DoseEvent]:
    tz = get_zone(patient.timezone)
    today = local_today(patient)
    start = datetime.combine(today, datetime.min.time(), tzinfo=tz)
    return list(
        db.session.scalars(
            select(DoseEvent)
            .where(
                # By medication, not item: a revised prescription keeps earlier doses on the old item.
                DoseEvent.patient_id == patient.id,
                DoseEvent.medication_id == item.medication_id,
                DoseEvent.scheduled_at >= start,
                DoseEvent.scheduled_at < start + timedelta(days=1),
            )
            .order_by(DoseEvent.scheduled_at)
        )
    )
