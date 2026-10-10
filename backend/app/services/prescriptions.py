"""Prescription draft -> active flow (plan.md 5.3)."""

import uuid
from datetime import time

from sqlalchemy import func, select

from app.errors import bad_request, conflict, not_found
from app.extensions import db
from app.models import (
    DoseSchedule,
    DoseScheduleTime,
    DoseWindow,
    Prescription,
    PrescriptionItem,
    User,
)
from app.services import inventory, medications, openfda, scheduling
from app.utils.time import get_zone, utcnow

ITEM_FIELDS = ("dose_quantity", "dose_unit", "route", "quantity_prescribed", "refills_authorized", "instructions")


def _verify(item: PrescriptionItem) -> dict:
    return openfda.verify_medication(item.medication)


def _apply_item_fields(item: PrescriptionItem, data: dict) -> None:
    for field in ITEM_FIELDS:
        if field in data:
            value = data[field]
            if isinstance(value, str):
                value = value.strip() or None
            setattr(item, field, value)


def _resolve_medication(data: dict, current: PrescriptionItem | None = None):
    name = data.get("name", current.medication.name if current else None)
    if not name:
        raise bad_request("NAME_REQUIRED", "Each item needs a medication name.")
    strength = data["strength"] if "strength" in data else (current.medication.strength if current else None)
    form = data["dosage_form"] if "dosage_form" in data else (current.medication.dosage_form if current else None)
    return medications.find_or_create(name, strength, form)


def create_draft(patient: User, data: dict) -> tuple[Prescription, dict]:
    next_version = (
        db.session.scalar(select(func.max(Prescription.version)).where(Prescription.patient_id == patient.id)) or 0
    ) + 1
    rx = Prescription(
        patient_id=patient.id,
        version=next_version,
        status="draft",
        effective_at=data.get("effective_at"),
        source_document_uri=data.get("source_document_uri"),
    )
    db.session.add(rx)
    verification = {}
    for item_data in data.get("items", []):
        item = PrescriptionItem(prescription=rx, medication=_resolve_medication(item_data))
        _apply_item_fields(item, item_data)
        db.session.add(item)
        db.session.flush()
        verification[item.id] = _verify(item)
    db.session.flush()
    return rx, verification


def require_draft(rx: Prescription) -> None:
    if rx.status != "draft":
        raise conflict(
            "PRESCRIPTION_NOT_DRAFT",
            "Only draft prescriptions can be edited. Use POST /prescriptions/{id}/revise to start a new version.",
            {"status": rx.status},
        )


def update_draft(rx: Prescription, data: dict) -> dict:
    require_draft(rx)
    for field in ("effective_at", "source_document_uri"):
        if field in data:
            setattr(rx, field, data[field])
    by_id = {item.id: item for item in rx.items}
    for item_id in data.get("remove_item_ids", []):
        item = by_id.get(item_id)
        if item is None:
            raise not_found("Prescription item")
        rx.items.remove(item)
    verification = {}
    for item_data in data.get("items", []):
        item_id = item_data.get("id")
        if item_id is not None:
            item = by_id.get(item_id)
            if item is None:
                raise not_found("Prescription item")
            if {"name", "strength", "dosage_form"} & item_data.keys():
                item.medication = _resolve_medication(item_data, item)
        else:
            item = PrescriptionItem(prescription=rx, medication=_resolve_medication(item_data))
            db.session.add(item)
        _apply_item_fields(item, item_data)
        db.session.flush()
        verification[item.id] = _verify(item)
    db.session.flush()
    return verification


def set_schedule(item: PrescriptionItem, data: dict) -> DoseSchedule:
    rx = item.prescription
    require_draft(rx)
    patient = db.session.get(User, rx.patient_id)
    times_data = data.get("times") or []
    if not times_data:
        raise bad_request("SCHEDULE_TIMES_REQUIRED", "A schedule needs at least one time.")

    resolved: list[tuple[time, DoseWindow]] = []
    for t in times_data:
        window = None
        if t.get("dose_window_id"):
            window = db.session.get(DoseWindow, t["dose_window_id"])
        elif t.get("window_kind"):
            window = db.session.scalar(
                select(DoseWindow).where(DoseWindow.patient_id == patient.id, DoseWindow.kind == t["window_kind"])
            )
        if window is None or window.patient_id != patient.id:
            raise bad_request("WINDOW_NOT_FOUND", "Each time needs a dose window that belongs to this patient.")
        local_time = t.get("local_time") or window.target_time
        if local_time is None:
            raise bad_request(
                "LOCAL_TIME_REQUIRED", f"'{window.name}' has no default time, so local_time is required."
            )
        resolved.append((local_time, window))
    if len({lt for lt, _ in resolved}) != len(resolved):
        raise bad_request("DUPLICATE_TIME", "Two schedule times can't be at the same local time.")

    if item.schedule is not None:
        db.session.delete(item.schedule)
        db.session.flush()
    schedule = DoseSchedule(
        prescription_item_id=item.id,
        frequency=data.get("frequency", "daily"),
        start_date=data.get("start_date") or utcnow().astimezone(get_zone(patient.timezone)).date(),
        end_date=data.get("end_date"),
        timezone=patient.timezone,
        active=False,
    )
    if schedule.end_date and schedule.end_date < schedule.start_date:
        raise bad_request("INVALID_DATE_RANGE", "end_date must be on or after start_date.")
    schedule.times = [DoseScheduleTime(local_time=lt, dose_window_id=w.id) for lt, w in resolved]
    db.session.add(schedule)
    db.session.flush()
    db.session.refresh(item)
    return schedule


def _activation_errors(rx: Prescription) -> dict:
    errors = {}
    if not rx.items:
        errors["items"] = ["A prescription needs at least one medication."]
    for item in rx.items:
        problems = []
        if item.dose_quantity is None:
            problems.append("dose_quantity is required")
        if not item.dose_unit:
            problems.append("dose_unit is required")
        if not item.instructions:
            problems.append("instructions are required")
        if item.schedule is None or not item.schedule.times:
            problems.append("a schedule with at least one time is required")
        if problems:
            errors[str(item.id)] = problems
    return errors


def activate(rx: Prescription, *, user_id: uuid.UUID, initialize_inventory: bool = True) -> dict:
    require_draft(rx)
    errors = _activation_errors(rx)
    if errors:
        raise bad_request("PRESCRIPTION_INCOMPLETE", "Finish these fields before activating.", errors)
    now = utcnow()

    warnings = []
    for item in rx.items:
        result = _verify(item)
        if result["status"] != "verified":
            warnings.append(
                {
                    "code": "MEDICATION_UNVERIFIED" if result["status"] == "unverified" else "OPENFDA_UNAVAILABLE",
                    "prescription_item_id": str(item.id),
                    "medication": item.medication.name,
                    "message": (
                        f"{item.medication.name} could not be verified against OpenFDA."
                        if result["status"] == "unverified"
                        else "OpenFDA could not be reached; verification was skipped."
                    ),
                }
            )

    previous = db.session.scalar(
        select(Prescription)
        .where(Prescription.patient_id == rx.patient_id, Prescription.status == "active")
        .with_for_update()
    )
    if previous is not None:
        old_schedule_ids = [i.schedule.id for i in previous.items if i.schedule is not None]
        for item in previous.items:
            if item.schedule is not None:
                item.schedule.active = False
        scheduling.delete_future_pending(old_schedule_ids, now, include_current=True)
        previous.status = "superseded"
        db.session.flush()

    rx.status = "active"
    rx.effective_at = rx.effective_at or now
    initialized = []
    for item in rx.items:
        item.schedule.active = True
        inv = inventory.ensure_inventory(rx.patient_id, item.medication_id, item.dose_unit)
        if initialize_inventory and inv.quantity_remaining is None and item.quantity_prescribed:
            inventory.set_quantity(
                inv, item.quantity_prescribed, created_by=user_id, note="initialized from prescription"
            )
            initialized.append(str(item.medication_id))
    db.session.flush()
    db.session.expire_all()
    created = scheduling.generate_for_patient(rx.patient_id, now)
    return {
        "warnings": warnings,
        "superseded_prescription_id": previous.id if previous else None,
        "dose_events_created": created,
        "inventory_initialized_for": initialized,
    }


def revise(rx: Prescription) -> Prescription:
    """Copy an active/superseded prescription into a new draft, including schedules."""
    if rx.status == "draft":
        raise conflict("PRESCRIPTION_IS_DRAFT", "This prescription is already a draft; edit it directly.")
    next_version = (
        db.session.scalar(select(func.max(Prescription.version)).where(Prescription.patient_id == rx.patient_id)) or 0
    ) + 1
    draft = Prescription(
        patient_id=rx.patient_id,
        version=next_version,
        status="draft",
        source_document_uri=rx.source_document_uri,
    )
    db.session.add(draft)
    for item in rx.items:
        copy = PrescriptionItem(prescription=draft, medication_id=item.medication_id)
        db.session.add(copy)
        for field in ITEM_FIELDS:
            setattr(copy, field, getattr(item, field))
        if item.schedule is not None:
            s = item.schedule
            copy.schedule = DoseSchedule(
                frequency=s.frequency,
                start_date=s.start_date,
                end_date=s.end_date,
                timezone=s.timezone,
                active=False,
                times=[DoseScheduleTime(local_time=t.local_time, dose_window_id=t.dose_window_id) for t in s.times],
            )
    db.session.flush()
    return draft


def seed_default_windows(patient_id: uuid.UUID) -> None:
    from app.models.enums import DEFAULT_WINDOWS

    for kind, name, target, before, after, missed in DEFAULT_WINDOWS:
        db.session.add(
            DoseWindow(
                patient_id=patient_id,
                name=name,
                kind=kind,
                target_time=time.fromisoformat(target) if target else None,
                on_time_before_min=before,
                on_time_after_min=after,
                missed_after_min=missed,
            )
        )
