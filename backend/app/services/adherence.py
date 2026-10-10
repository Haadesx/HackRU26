"""Dose classification and the dose_outcomes hypertable (plan.md 5.5, 5.6)."""

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from app.extensions import db
from app.models import DoseEvent, DoseOutcome
from app.utils.time import utcnow


def classify(event: DoseEvent, taken_at: datetime) -> str:
    """taken_at <= on_time_end -> taken_on_time; otherwise taken_late (including after a miss)."""
    return "taken_on_time" if taken_at <= event.on_time_end else "taken_late"


def timing_label(event: DoseEvent, at: datetime) -> str:
    """For scan responses: on_time | late | after_missed."""
    if event.status == "missed":
        return "after_missed"
    if at <= event.on_time_end:
        return "on_time"
    return "late"


def delay_minutes(event: DoseEvent) -> int | None:
    if event.taken_at is None:
        return None
    return round((event.taken_at - event.scheduled_at).total_seconds() / 60)


def upsert_outcome(event: DoseEvent) -> None:
    """One row per dose; a late confirmation after a miss replaces the missed row."""
    values = {
        "scheduled_at": event.scheduled_at,
        "dose_event_id": event.id,
        "patient_id": event.patient_id,
        "medication_id": event.medication_id,
        "status": event.status,
        "dose_mismatch": event.dose_mismatch,
        "delay_minutes": delay_minutes(event) if event.status in ("taken_on_time", "taken_late") else None,
        "recorded_at": utcnow(),
    }
    stmt = insert(DoseOutcome).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["dose_event_id", "scheduled_at"],
        set_={k: stmt.excluded[k] for k in ("status", "dose_mismatch", "delay_minutes", "recorded_at")},
    )
    db.session.execute(stmt)
