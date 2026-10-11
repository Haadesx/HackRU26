"""Background job bodies (plan.md 7). Each takes `now` so tests can drive the clock.

All row selection uses FOR UPDATE SKIP LOCKED or unique constraints, so two workers
running at once cannot double-send.
"""

import logging
from datetime import datetime

from flask import current_app
from sqlalchemy import select

from app.extensions import db
from app.models import DoseEvent, NotificationDelivery, Reminder
from app.services import doses, notifications, scheduling
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def generate_dose_events(now: datetime | None = None) -> int:
    created = scheduling.generate_all(now or utcnow())
    db.session.commit()
    return created


def mark_missed_doses(now: datetime | None = None) -> int:
    hook = None
    if current_app.config.get("HUB_ENABLED"):
        from app.hub.routes import on_missed as hook
    count = doses.mark_missed(now or utcnow(), on_missed=hook)
    db.session.commit()
    return count


def dispatch_due_reminders(now: datetime | None = None, batch: int = 200) -> int:
    now = now or utcnow()
    reminders = db.session.scalars(
        select(Reminder)
        .where(Reminder.status == "pending", Reminder.scheduled_at <= now)
        .order_by(Reminder.scheduled_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    sent = 0
    for reminder in reminders:
        if reminder.kind in ("dose_due", "dose_followup") and reminder.dose_event_id:
            event = db.session.get(DoseEvent, reminder.dose_event_id)
            # Don't nag about doses that are done, or send stale reminders after an outage.
            if event is None or event.status != "pending" or now > event.missed_after:
                reminder.status = "cancelled"
                continue
        notifications.dispatch(reminder)
        sent += 1
    db.session.commit()
    return sent


def retry_failed_deliveries(now: datetime | None = None, batch: int = 100) -> int:
    max_attempts = current_app.config["DELIVERY_MAX_ATTEMPTS"]
    deliveries = db.session.scalars(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.status == "failed",
            NotificationDelivery.attempts < max_attempts,
            NotificationDelivery.channel.in_(("sms", "push")),
        )
        .limit(batch)
        .with_for_update(skip_locked=True)
    ).all()
    for d in deliveries:
        notifications.retry(d)
        if d.status == "sent" and d.reminder.status == "failed":
            d.reminder.status = "sent"
    db.session.commit()
    return len(deliveries)
