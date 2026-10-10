"""Model -> JSON-ready dict. Datetimes/Decimals/UUIDs are converted by app.json.ApiJSONProvider."""

from app.models import (
    CaregiverLink,
    DoseEvent,
    DoseSchedule,
    DoseWindow,
    InventoryTransaction,
    Medication,
    MedicationInventory,
    NotificationDelivery,
    Prescription,
    PrescriptionItem,
    RefillRequest,
    User,
)


def user(u: User, private: bool = True) -> dict:
    data = {"id": u.id, "name": u.name, "email": u.email, "role": u.role, "timezone": u.timezone}
    if private:
        data.update(
            {"phone": u.phone, "sms_enabled": u.sms_enabled, "push_enabled": u.push_enabled, "created_at": u.created_at}
        )
    return data


def caregiver_link(link: CaregiverLink, include_code: bool = False) -> dict:
    data = {
        "id": link.id,
        "patient": user(link.patient, private=False),
        "caregiver": user(link.caregiver, private=False),
        "status": link.status,
        "permissions": link.permissions,
        "created_at": link.created_at,
    }
    if include_code:
        data["invite_code"] = link.invite_code
        data["invite_expires_at"] = link.invite_expires_at
    return data


def medication(m: Medication) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "strength": m.strength,
        "dosage_form": m.dosage_form,
        "verified": m.verified,
        "verified_at": m.verified_at,
        "openfda_id": m.openfda_id,
        "rxcui": m.rxcui,
    }


def window(w: DoseWindow) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "kind": w.kind,
        "target_time": w.target_time,
        "on_time_before_min": w.on_time_before_min,
        "on_time_after_min": w.on_time_after_min,
        "missed_after_min": w.missed_after_min,
        "updated_at": w.updated_at,
    }


def schedule(s: DoseSchedule | None) -> dict | None:
    if s is None:
        return None
    return {
        "id": s.id,
        "frequency": s.frequency,
        "start_date": s.start_date,
        "end_date": s.end_date,
        "timezone": s.timezone,
        "active": s.active,
        "times": [
            {"id": t.id, "local_time": t.local_time, "dose_window_id": t.dose_window_id, "window_name": t.window.name}
            for t in s.times
        ],
    }


def prescription_item(i: PrescriptionItem, verification: dict | None = None) -> dict:
    data = {
        "id": i.id,
        "medication": medication(i.medication),
        "dose_quantity": i.dose_quantity,
        "dose_unit": i.dose_unit,
        "route": i.route,
        "quantity_prescribed": i.quantity_prescribed,
        "refills_authorized": i.refills_authorized,
        "instructions": i.instructions,
        "schedule": schedule(i.schedule),
    }
    if verification is not None:
        data["verification"] = verification
    return data


def prescription(rx: Prescription, verification: dict | None = None) -> dict:
    verification = verification or {}
    return {
        "id": rx.id,
        "patient_id": rx.patient_id,
        "version": rx.version,
        "status": rx.status,
        "effective_at": rx.effective_at,
        "source_document_uri": rx.source_document_uri,
        "created_at": rx.created_at,
        "items": [prescription_item(i, verification.get(i.id)) for i in rx.items],
    }


def prescription_summary(rx: Prescription) -> dict:
    return {
        "id": rx.id,
        "version": rx.version,
        "status": rx.status,
        "effective_at": rx.effective_at,
        "created_at": rx.created_at,
        "item_count": len(rx.items),
    }


def dose_event(e: DoseEvent) -> dict:
    item = e.item
    return {
        "id": e.id,
        "patient_id": e.patient_id,
        "prescription_item_id": e.prescription_item_id,
        "medication": {"id": e.medication.id, "name": e.medication.name, "strength": e.medication.strength},
        "expected_quantity": item.dose_quantity,
        "dose_unit": item.dose_unit,
        "instructions": item.instructions,
        "window_name": e.window_name,
        "scheduled_at": e.scheduled_at,
        "on_time_start": e.on_time_start,
        "on_time_end": e.on_time_end,
        "missed_after": e.missed_after,
        "confirm_deadline": e.confirm_deadline,
        "status": e.status,
        "dose_mismatch": e.dose_mismatch,
        "confirmed_after_missed": e.confirmed_after_missed,
        "confirmation_method": e.confirmation_method,
        "confirmed_at": e.confirmed_at,
        "taken_at": e.taken_at,
        "quantity_taken": e.quantity_taken,
        "observation_event_id": e.observation_event_id,
    }


def inventory(inv: MedicationInventory, estimated_days_remaining=None) -> dict:
    return {
        "id": inv.id,
        "medication": medication(inv.medication),
        "quantity_remaining": inv.quantity_remaining,
        "quantity_unit": inv.quantity_unit,
        "tracked": inv.quantity_remaining is not None,
        "estimated_days_remaining": estimated_days_remaining,
        "last_reconciled_at": inv.last_reconciled_at,
        "updated_at": inv.updated_at,
    }


def inventory_transaction(t: InventoryTransaction) -> dict:
    return {
        "id": t.id,
        "delta": t.delta,
        "reason": t.reason,
        "dose_event_id": t.dose_event_id,
        "refill_request_id": t.refill_request_id,
        "created_by": t.created_by,
        "note": t.note,
        "created_at": t.created_at,
    }


def refill(r: RefillRequest) -> dict:
    return {
        "id": r.id,
        "patient_id": r.patient_id,
        "prescription_item_id": r.prescription_item_id,
        "medication": medication(r.item.medication),
        "status": r.status,
        "requested_by": r.requested_by,
        "appointment_at": r.appointment_at,
        "pharmacy_or_provider": r.pharmacy_or_provider,
        "fulfilled_at": r.fulfilled_at,
        "quantity_added": r.quantity_added,
        "caregiver_notified_at": r.caregiver_notified_at,
        "created_at": r.created_at,
    }


def notification(d: NotificationDelivery) -> dict:
    r = d.reminder
    return {
        "id": d.id,
        "kind": r.kind,
        "title": r.title,
        "body": r.body,
        "patient_id": r.patient_id,
        "dose_event_id": r.dose_event_id,
        "refill_request_id": r.refill_request_id,
        "created_at": d.sent_at or d.created_at,
        "read_at": d.read_at,
        "read": d.read_at is not None,
    }
