"""Tap-to-confirm, skip, and missed-dose marking (plan.md 5.5, 5.6)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from app.errors import bad_request, conflict, not_found
from app.extensions import db
from app.models import DoseEvent, Reminder, User, VisionObservation
from app.services import adherence, inventory, notifications
from app.utils.time import utcnow


def lock_event(dose_id: uuid.UUID) -> DoseEvent:
    event = db.session.scalar(select(DoseEvent).where(DoseEvent.id == dose_id).with_for_update())
    if event is None:
        raise not_found("Dose")
    return event


def confirm(
    event: DoseEvent,
    *,
    user_id: uuid.UUID,
    observation_event_id: uuid.UUID | None,
    quantity_taken: Decimal | None,
    now: datetime | None = None,
) -> dict:
    """Mark a dose taken. Caller must already hold the row lock and have checked patient access."""
    now = now or utcnow()
    was_missed = event.status == "missed"
    if event.status not in ("pending", "missed"):
        raise conflict("DOSE_NOT_CONFIRMABLE", f"Dose is already {event.status}.", {"status": event.status})
    if now > event.confirm_deadline:
        raise conflict(
            "CONFIRM_WINDOW_CLOSED",
            "This dose can no longer be confirmed.",
            {"confirm_deadline": event.confirm_deadline.isoformat()},
        )

    observation = None
    if observation_event_id is not None:
        observation = db.session.scalar(
            select(VisionObservation).where(
                VisionObservation.event_id == observation_event_id,
                VisionObservation.patient_id == event.patient_id,
            )
        )
        if observation is None:
            raise bad_request("OBSERVATION_NOT_FOUND", "No scan with that observation_event_id for this patient.")
        if observation.medication_id is not None and observation.medication_id != event.medication_id:
            raise bad_request("OBSERVATION_MISMATCH", "That scan is for a different medication.")
        taken_at = observation.observed_at
        method = "scan"
        if quantity_taken is None:
            quantity_taken = observation.quantity
    else:
        taken_at = now
        method = "manual"

    if taken_at < event.on_time_start:
        raise conflict(
            "DOSE_NOT_DUE",
            "This dose isn't due yet.",
            {"on_time_start": event.on_time_start.isoformat()},
        )

    item = event.item
    if quantity_taken is None:
        quantity_taken = item.dose_quantity
    quantity_taken = Decimal(quantity_taken)
    if quantity_taken <= 0:
        raise bad_request("INVALID_QUANTITY", "quantity_taken must be greater than 0.")

    event.status = adherence.classify(event, taken_at)
    event.taken_at = taken_at
    event.confirmed_at = now
    event.confirmation_method = method
    event.quantity_taken = quantity_taken
    event.observation_event_id = observation_event_id
    event.confirmed_after_missed = was_missed
    event.dose_mismatch = item.dose_quantity is not None and quantity_taken != item.dose_quantity
    if observation is not None and observation.dose_event_id is None:
        observation.dose_event_id = event.id

    inventory_result = {"tracked": False, "quantity_remaining": None, "warning": None}
    try:
        with db.session.begin_nested():
            txn = inventory.apply_transaction(
                event.patient_id,
                event.medication_id,
                -quantity_taken,
                "dose",
                dose_event_id=event.id,
                created_by=user_id,
            )
        if txn is not None:
            inv = inventory.get_inventory(event.patient_id, event.medication_id)
            inventory_result = {"tracked": True, "quantity_remaining": inv.quantity_remaining, "warning": None}
    except inventory.InsufficientStock:
        # The dose is still recorded; recorded stock is already wrong and needs a manual correction.
        inventory_result = {"tracked": True, "quantity_remaining": None, "warning": "insufficient_recorded_stock"}

    adherence.upsert_outcome(event)
    notifications.cancel_dose_reminders(event.id)
    _post_confirm_alerts(event, item, was_missed)
    db.session.flush()
    return {"inventory": inventory_result}


def _post_confirm_alerts(event: DoseEvent, item, was_missed: bool) -> None:
    label = notifications.med_label(item)
    if event.dose_mismatch:
        taken = notifications.qty_text(event.quantity_taken, item.dose_unit)
        prescribed = notifications.qty_text(item.dose_quantity, item.dose_unit)
        body = f"{label}: {taken} taken, {prescribed} prescribed."
        recipients = [event.patient_id] + [c.id for c in notifications.alert_caregivers(event.patient_id)]
        for rid in recipients:
            notifications.create_reminder(
                patient_id=event.patient_id,
                recipient_id=rid,
                kind="dose_mismatch_alert",
                title="Different dose amount recorded",
                body=body,
                dose_event_id=event.id,
            )
    if was_missed:
        alerted = db.session.scalars(
            select(Reminder.recipient_user_id).where(
                Reminder.dose_event_id == event.id,
                Reminder.kind == "missed_dose_alert",
                Reminder.recipient_user_id != event.patient_id,
            )
        ).all()
        patient_name = db.session.get(User, event.patient_id).name
        for rid in alerted:
            notifications.create_reminder(
                patient_id=event.patient_id,
                recipient_id=rid,
                kind="missed_dose_resolved",
                title=f"{patient_name} confirmed a missed dose",
                body=f"{patient_name} confirmed taking {label} (marked late).",
                dose_event_id=event.id,
            )


def skip(event: DoseEvent, now: datetime | None = None) -> None:
    now = now or utcnow()
    if event.status != "pending":
        raise conflict("DOSE_NOT_SKIPPABLE", f"Dose is already {event.status}.", {"status": event.status})
    event.status = "skipped"
    event.confirmed_at = now
    adherence.upsert_outcome(event)
    notifications.cancel_dose_reminders(event.id)
    db.session.flush()


def mark_missed(now: datetime | None = None, batch: int = 200) -> int:
    """Worker job: pending doses past missed_after become missed; caregivers are alerted."""
    now = now or utcnow()
    events = db.session.scalars(
        select(DoseEvent)
        .where(DoseEvent.status == "pending", DoseEvent.missed_after < now)
        .order_by(DoseEvent.missed_after)
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    for event in events:
        event.status = "missed"
        adherence.upsert_outcome(event)
        notifications.cancel_dose_reminders(event.id)
        item = event.item
        label = notifications.med_label(item)
        patient = db.session.get(User, event.patient_id)
        at = notifications.local_hhmm(event.scheduled_at, patient.timezone)
        qty = notifications.qty_text(item.dose_quantity, item.dose_unit)
        for caregiver in notifications.alert_caregivers(event.patient_id):
            notifications.create_reminder(
                patient_id=event.patient_id,
                recipient_id=caregiver.id,
                kind="missed_dose_alert",
                title=f"{patient.name} missed a dose",
                body=f"{patient.name} hasn't confirmed the {at} dose of {label} ({qty}).",
                dose_event_id=event.id,
            )
        notifications.create_reminder(
            patient_id=event.patient_id,
            recipient_id=event.patient_id,
            kind="missed_dose_alert",
            title=f"Missed dose: {label}",
            body=f"Your {at} dose of {label} was marked missed. If you took it, you can still confirm it.",
            dose_event_id=event.id,
        )
    db.session.flush()
    return len(events)
