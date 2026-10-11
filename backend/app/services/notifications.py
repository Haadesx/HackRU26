"""Reminders and fan-out to channels (plan.md 5.7, 5.8).

A reminder is one logical message to one recipient. dispatch() creates one
notification_deliveries row per channel (in_app always; push per web token; SMS if
enabled and a phone is set) and sends each independently.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from flask import current_app
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.extensions import db
from app.json import to_number
from app.models import (
    CaregiverLink,
    DoseEvent,
    NotificationDelivery,
    PrescriptionItem,
    PushToken,
    Reminder,
    User,
)
from app.services.channels import ChannelError, InvalidRecipient
from app.services.channels import push as push_channel
from app.services.channels import sms as sms_channel
from app.utils.time import get_zone, utcnow

log = logging.getLogger(__name__)


# ---------- recipients ----------


def alert_caregivers(patient_id: uuid.UUID) -> list[User]:
    """Caregivers with an active link and receive_alerts permission."""
    links = db.session.scalars(
        select(CaregiverLink).where(CaregiverLink.patient_id == patient_id, CaregiverLink.status == "active")
    ).all()
    return [link.caregiver for link in links if link.permissions.get("receive_alerts", False)]


# ---------- text helpers ----------


def qty_text(value: Decimal | None, unit: str | None) -> str:
    if value is None:
        return "your dose"
    n = to_number(value)
    unit = unit or ""
    if unit and n != 1 and not unit.endswith("s"):
        unit = unit + "s"
    return f"{n} {unit}".strip()


def med_label(item: PrescriptionItem) -> str:
    med = item.medication
    return f"{med.name} {med.strength}" if med.strength else med.name


def local_hhmm(dt: datetime, tz_name: str) -> str:
    return dt.astimezone(get_zone(tz_name)).strftime("%H:%M")


# ---------- creation ----------


def create_reminder(
    *,
    patient_id: uuid.UUID,
    recipient_id: uuid.UUID,
    kind: str,
    title: str,
    body: str,
    scheduled_at: datetime | None = None,
    dose_event_id: uuid.UUID | None = None,
    refill_request_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Insert a pending reminder. Dose reminders are idempotent per (dose, kind, recipient)."""
    values = {
        "id": uuid.uuid4(),
        "patient_id": patient_id,
        "recipient_user_id": recipient_id,
        "kind": kind,
        "title": title,
        "body": body,
        "scheduled_at": scheduled_at or utcnow(),
        "status": "pending",
        "dose_event_id": dose_event_id,
        "refill_request_id": refill_request_id,
        "created_at": utcnow(),
    }
    stmt = insert(Reminder).values(values)
    if dose_event_id is not None:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["dose_event_id", "kind", "recipient_user_id"],
            index_where=Reminder.dose_event_id.isnot(None),
        )
    return db.session.execute(stmt.returning(Reminder.id)).scalar()


def create_dose_reminders(event: DoseEvent, item: PrescriptionItem, now: datetime) -> None:
    """dose_due at scheduled_at and dose_followup at on_time_end, while those times are still useful."""
    patient = db.session.get(User, event.patient_id)
    label = med_label(item)
    qty = qty_text(item.dose_quantity, item.dose_unit)
    at = local_hhmm(event.scheduled_at, patient.timezone)
    if event.on_time_end > now:
        create_reminder(
            patient_id=event.patient_id,
            recipient_id=event.patient_id,
            kind="dose_due",
            title=f"Time for {label}",
            body=f"Take {qty} of {label} ({event.window_name or 'scheduled'} dose, {at}).",
            scheduled_at=max(event.scheduled_at, now),
            dose_event_id=event.id,
        )
        create_reminder(
            patient_id=event.patient_id,
            recipient_id=event.patient_id,
            kind="dose_followup",
            title=f"{label} is still due",
            body=f"You haven't confirmed your {at} dose of {label} yet. Take {qty} and tap to confirm.",
            scheduled_at=event.on_time_end,
            dose_event_id=event.id,
        )


def cancel_dose_reminders(dose_event_id: uuid.UUID, kinds=("dose_due", "dose_followup")) -> None:
    for reminder in db.session.scalars(
        select(Reminder).where(
            Reminder.dose_event_id == dose_event_id, Reminder.kind.in_(kinds), Reminder.status == "pending"
        )
    ):
        reminder.status = "cancelled"


# ---------- dispatch ----------

# (kind, recipient is the patient) -> channels. Default: all channels.
_IN_APP_ONLY = {("missed_dose_alert", True)}


def _channels_for(reminder: Reminder, recipient: User) -> list[str]:
    if (reminder.kind, recipient.id == reminder.patient_id) in _IN_APP_ONLY:
        return ["in_app"]
    return ["in_app", "push", "sms"]


def _send_delivery(delivery: NotificationDelivery, reminder: Reminder, recipient: User) -> None:
    delivery.attempts += 1
    try:
        if delivery.channel == "in_app":
            pass
        elif delivery.channel == "sms":
            sms_channel.send(recipient.phone, f"{reminder.title}: {reminder.body}")
        elif delivery.channel == "push":
            token = db.session.get(PushToken, delivery.push_token_id) if delivery.push_token_id else None
            if token is None:
                raise InvalidRecipient("push token no longer registered")
            push_channel.send(
                token.token,
                reminder.title,
                reminder.body,
                {"reminder_id": str(reminder.id), "kind": reminder.kind, "dose_event_id": str(reminder.dose_event_id or "")},
            )
            token.last_used_at = utcnow()
        delivery.status = "sent"
        delivery.sent_at = utcnow()
        delivery.error = None
    except InvalidRecipient as exc:
        delivery.status = "failed"
        delivery.error = str(exc)[:500]
        delivery.attempts = current_app.config["DELIVERY_MAX_ATTEMPTS"]  # never retry
        if delivery.channel == "push" and delivery.push_token_id:
            token = db.session.get(PushToken, delivery.push_token_id)
            if token is not None:
                db.session.delete(token)
            delivery.push_token_id = None
    except ChannelError as exc:
        delivery.status = "failed"
        delivery.error = str(exc)[:500]
        log.warning("Delivery %s via %s failed: %s", delivery.id, delivery.channel, exc)


def dispatch(reminder: Reminder) -> None:
    recipient = db.session.get(User, reminder.recipient_user_id)
    channels = _channels_for(reminder, recipient)
    deliveries: list[NotificationDelivery] = [NotificationDelivery(channel="in_app", status="pending", attempts=0)]
    if "push" in channels and recipient.push_enabled and push_channel.configured():
        for token in db.session.scalars(select(PushToken).where(PushToken.user_id == recipient.id)):
            deliveries.append(
                NotificationDelivery(channel="push", status="pending", attempts=0, push_token_id=token.id)
            )
    if "sms" in channels and recipient.sms_enabled and recipient.phone and sms_channel.configured():
        deliveries.append(NotificationDelivery(channel="sms", status="pending", attempts=0))
    for d in deliveries:
        reminder.deliveries.append(d)
    db.session.flush()
    for d in deliveries:
        _send_delivery(d, reminder, recipient)
    reminder.status = "sent" if any(d.status == "sent" for d in deliveries) else "failed"
    reminder.sent_at = utcnow()


def retry(delivery: NotificationDelivery) -> None:
    reminder = delivery.reminder
    recipient = db.session.get(User, reminder.recipient_user_id)
    _send_delivery(delivery, reminder, recipient)
