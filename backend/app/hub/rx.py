"""Adding/removing a dashboard medication = a new prescription version (history is kept)."""

from datetime import time

from sqlalchemy import select

from app.errors import ApiError
from app.extensions import db
from app.models import DoseWindow, Prescription, User
from app.services import prescriptions as rx_service


def _active(patient: User) -> Prescription | None:
    return db.session.scalar(
        select(Prescription).where(Prescription.patient_id == patient.id, Prescription.status == "active")
    )


def schedule_spec(patient: User, times: list[str]) -> list[dict]:
    """Map "HH:MM" to the patient's preset window with that target time, else the generic window."""
    presets = {
        w.target_time: w
        for w in db.session.scalars(
            select(DoseWindow).where(DoseWindow.patient_id == patient.id, DoseWindow.kind.in_(("breakfast", "lunch", "dinner", "bedtime")))
        )
        if w.target_time is not None
    }
    spec = []
    for t in times:
        local = time.fromisoformat(t)
        if local in presets:
            spec.append({"dose_window_id": presets[local].id})
        else:
            spec.append({"window_kind": "generic", "local_time": local})
    return spec


def add_medication(patient: User, item_data: dict, times: list[str]) -> dict:
    """Create a new active version that includes the new item. Returns activation result."""
    active = _active(patient)
    if active is not None:
        for item in active.items:
            med = item.medication
            if med.name.lower() == item_data["name"].lower() and (med.strength or "") == (item_data.get("strength") or ""):
                raise ApiError(409, "ALREADY_TRACKED", f"{med.name} {med.strength or ''} is already being tracked. Use “Refill picked up” instead.".replace("  ", " "))
        draft = rx_service.revise(active)
    else:
        draft, _ = rx_service.create_draft(patient, {"items": []})
    before = {i.id for i in draft.items}
    rx_service.update_draft(draft, {"items": [item_data]})
    new_item = next(i for i in draft.items if i.id not in before)
    rx_service.set_schedule(new_item, {"times": schedule_spec(patient, times)})
    db.session.refresh(draft)
    result = rx_service.activate(draft, user_id=patient.id, initialize_inventory=True)
    return {"item_medication_id": new_item.medication_id, **result}


def change_schedule(patient: User, medication_id, times: list[str]) -> dict:
    """New dose times for one medication = a new prescription version.

    Doses already taken/missed/skipped keep their history; not-yet-taken doses at the old
    times are replaced by doses at the new times (same rules as any re-activation).
    """
    active = _active(patient)
    if active is None or not any(i.medication_id == medication_id for i in active.items):
        raise ApiError(404, "MEDICATION_NOT_FOUND", "That medication no longer exists.")
    draft = rx_service.revise(active)
    item = next(i for i in draft.items if i.medication_id == medication_id)
    old = item.schedule
    rx_service.set_schedule(
        item,
        {
            "frequency": old.frequency if old else "daily",
            "start_date": old.start_date if old else None,
            "end_date": old.end_date if old else None,
            "times": schedule_spec(patient, times),
        },
    )
    db.session.refresh(draft)
    return rx_service.activate(draft, user_id=patient.id, initialize_inventory=False)


def remove_medication(patient: User, medication_id) -> None:
    active = _active(patient)
    if active is None:
        return
    keep = [i for i in active.items if i.medication_id != medication_id]
    if not keep:
        rx_service.deactivate(patient.id)
        return
    draft = rx_service.revise(active)
    remove_ids = [i.id for i in draft.items if i.medication_id == medication_id]
    rx_service.update_draft(draft, {"remove_item_ids": remove_ids})
    db.session.refresh(draft)
    rx_service.activate(draft, user_id=patient.id, initialize_inventory=False)
