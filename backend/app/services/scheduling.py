"""Materialize concrete dose_events from schedules over a rolling horizon (plan.md 5.4).

Window bounds are snapshotted onto each event at generation, so editing a window later
never rewrites history. Inserts use ON CONFLICT (schedule_id, scheduled_at) DO NOTHING,
so running generation repeatedly is safe.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import (
    DoseEvent,
    DoseSchedule,
    DoseScheduleTime,
    Prescription,
    PrescriptionItem,
    User,
)
from app.services import notifications
from app.utils.time import get_zone, utcnow

CONFIRM_CAP = timedelta(hours=24)


def _frequency_ok(schedule: DoseSchedule, d: date) -> bool:
    days = (d - schedule.start_date).days
    if days < 0:
        return False
    if schedule.end_date and d > schedule.end_date:
        return False
    if schedule.frequency == "daily":
        return True
    if schedule.frequency == "every_other_day":
        return days % 2 == 0
    if schedule.frequency == "weekly":
        return days % 7 == 0
    return False


def schedule_occurrences(schedule: DoseSchedule, first: date, last: date) -> list[tuple[datetime, DoseScheduleTime]]:
    """All (scheduled_at UTC, schedule_time) between local dates first..last inclusive, sorted."""
    tz = get_zone(schedule.timezone)
    out = []
    d = first
    while d <= last:
        if _frequency_ok(schedule, d):
            for st in schedule.times:
                local = datetime.combine(d, st.local_time, tzinfo=tz)
                out.append((local.astimezone(timezone.utc), st))
        d += timedelta(days=1)
    out.sort(key=lambda pair: pair[0])
    return out


def build_event_rows(schedule: DoseSchedule, now: datetime, horizon: timedelta) -> list[dict]:
    """Rows for events that are still actionable (missed_after > now) and start before now + horizon."""
    tz = get_zone(schedule.timezone)
    first = max(schedule.start_date, (now.astimezone(tz) - timedelta(days=1)).date())
    last_gen = (now + horizon).astimezone(tz).date()
    occurrences = schedule_occurrences(schedule, first, last_gen + timedelta(days=8))
    item = schedule.item
    rows = []
    for i, (scheduled_at, st) in enumerate(occurrences):
        if scheduled_at > now + horizon:
            break
        w = st.window
        missed_after = scheduled_at + timedelta(minutes=w.missed_after_min)
        if missed_after <= now:
            continue
        next_at = occurrences[i + 1][0] if i + 1 < len(occurrences) else scheduled_at + CONFIRM_CAP
        confirm_deadline = max(missed_after, min(next_at, scheduled_at + CONFIRM_CAP))
        rows.append(
            {
                "id": uuid.uuid4(),
                "patient_id": item.prescription.patient_id,
                "prescription_item_id": item.id,
                "medication_id": item.medication_id,
                "schedule_id": schedule.id,
                "schedule_time_id": st.id,
                "scheduled_at": scheduled_at,
                "on_time_start": scheduled_at - timedelta(minutes=w.on_time_before_min),
                "on_time_end": scheduled_at + timedelta(minutes=w.on_time_after_min),
                "missed_after": missed_after,
                "confirm_deadline": confirm_deadline,
                "window_name": w.name,
                "status": "pending",
                "dose_mismatch": False,
                "confirmed_after_missed": False,
                "created_at": now,
            }
        )
    return rows


def _active_schedules(patient_id: uuid.UUID) -> list[DoseSchedule]:
    return list(
        db.session.scalars(
            select(DoseSchedule)
            .join(PrescriptionItem, DoseSchedule.prescription_item_id == PrescriptionItem.id)
            .join(Prescription, PrescriptionItem.prescription_id == Prescription.id)
            .where(
                Prescription.patient_id == patient_id,
                Prescription.status == "active",
                DoseSchedule.active.is_(True),
            )
            .options(
                selectinload(DoseSchedule.times).selectinload(DoseScheduleTime.window),
                selectinload(DoseSchedule.item).selectinload(PrescriptionItem.medication),
                selectinload(DoseSchedule.item).selectinload(PrescriptionItem.prescription),
            )
        )
    )


def generate_for_patient(patient_id: uuid.UUID, now: datetime | None = None) -> int:
    """Create upcoming dose events (and their patient reminders). Returns the number of new events."""
    now = now or utcnow()
    horizon = timedelta(hours=current_app.config["DOSE_HORIZON_HOURS"])
    created = 0
    for schedule in _active_schedules(patient_id):
        rows = build_event_rows(schedule, now, horizon)
        if not rows:
            continue
        # Skip times already covered for the same medication by another schedule
        # (e.g. a dose taken under a superseded prescription version).
        existing = set(
            db.session.execute(
                select(DoseEvent.scheduled_at).where(
                    DoseEvent.patient_id == patient_id,
                    DoseEvent.medication_id == schedule.item.medication_id,
                    DoseEvent.schedule_id != schedule.id,
                    DoseEvent.scheduled_at.in_([r["scheduled_at"] for r in rows]),
                )
            ).scalars()
        )
        rows = [r for r in rows if r["scheduled_at"] not in existing]
        if not rows:
            continue
        inserted_ids = list(
            db.session.execute(
                insert(DoseEvent)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["schedule_id", "scheduled_at"])
                .returning(DoseEvent.id)
            ).scalars()
        )
        created += len(inserted_ids)
        if inserted_ids:
            events = db.session.scalars(select(DoseEvent).where(DoseEvent.id.in_(inserted_ids))).all()
            for event in events:
                notifications.create_dose_reminders(event, schedule.item, now)
    db.session.flush()
    return created


def generate_all(now: datetime | None = None) -> int:
    now = now or utcnow()
    patient_ids = db.session.scalars(
        select(Prescription.patient_id).where(Prescription.status == "active").distinct()
    ).all()
    return sum(generate_for_patient(pid, now) for pid in patient_ids)


def delete_future_pending(schedule_ids: list[uuid.UUID], now: datetime, include_current: bool = False) -> int:
    """Remove pending events that have not happened yet (their reminders cascade).

    include_current=True also removes pending events whose window is still open
    (used when a prescription is superseded; the new version regenerates them).
    """
    if not schedule_ids:
        return 0
    cutoff = DoseEvent.missed_after > now if include_current else DoseEvent.scheduled_at > now
    result = db.session.execute(
        delete(DoseEvent).where(
            DoseEvent.schedule_id.in_(schedule_ids),
            DoseEvent.status == "pending",
            DoseEvent.observation_event_id.is_(None),
            cutoff,
        )
    )
    return result.rowcount or 0


def regenerate_future(patient_id: uuid.UUID, now: datetime | None = None) -> int:
    """After a window/timezone edit: drop not-yet-due pending events and rebuild them."""
    now = now or utcnow()
    schedule_ids = [s.id for s in _active_schedules(patient_id)]
    delete_future_pending(schedule_ids, now)
    db.session.flush()
    db.session.expire_all()
    return generate_for_patient(patient_id, now)


def patient_timezone(patient_id: uuid.UUID) -> str:
    return db.session.get(User, patient_id).timezone
