"""Scan-vs-prescription verification for the dashboard.

Turns a scan's read fields into a caregiver-facing safety result by comparing against the
patient's tracked medications and today's dose events. Read-only: it never records a dose and
never treats a name/schedule guess as positive bottle verification.

Statuses: ``uncertain`` · ``wrong_medication`` · ``strength_mismatch`` · ``due_now`` ·
``already_taken`` · ``not_due``. Exactly one is returned; ``can_log`` is true only for
``due_now`` (the UI must still require an explicit confirm action).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from rapidfuzz import fuzz
from sqlalchemy import select

from app.extensions import db
from app.models import DoseEvent
from app.hub import state as hub_state
from app.services.normalize import normalize_strength
from app.utils.time import get_zone, utcnow

TAKEN = ("taken_on_time", "taken_late")
OPEN = ("pending", "missed")
NAME_MATCH_MIN = 88  # rapidfuzz ratio
RECENT_TAKEN_HOURS = 6  # a dose confirmed this recently means "don't take another"


def _now() -> datetime:
    # Use the app clock so tests and scheduled jobs share one time source.
    return utcnow()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _local_hhmm(patient, value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(get_zone(patient.timezone)).strftime("%H:%M")


def _scan_text(scan) -> tuple[str, str, str, str]:
    fields = scan.fields or {}
    name = fields.get("name") or {}
    strength = fields.get("strength") or {}
    return (
        str(name.get("value") or "").strip(),
        str(name.get("state") or "missing"),
        str(strength.get("value") or "").strip(),
        str(strength.get("state") or "missing"),
    )


def _match_tracked(patient, name: str):
    """Best tracked item by name (exact casefold first, then fuzzy), preferring a strength match."""
    best = None
    for hm, item in hub_state.tracked(patient):
        med_name = _norm_name(item.medication.name)
        exact = med_name == name
        score = 100 if exact else fuzz.ratio(med_name, name)
        if score < NAME_MATCH_MIN:
            continue
        rank = (score, 1 if exact else 0)
        if best is None or rank > best[0]:
            best = (rank, hm, item)
    return best


def scan_verification(patient, scan) -> Optional[dict]:
    """Verification block for a scan (JSON-safe). ``None`` when the scan has no read name."""
    name_raw, name_state, strength_text, _ = _scan_text(scan)
    if not name_raw or name_state == "missing":
        return {
            "status": "uncertain",
            "can_log": False,
            "message": "We couldn't read the medication name clearly. Take another photo, or check the label.",
        }

    scanned_strength = normalize_strength(strength_text) if strength_text else None
    best = _match_tracked(patient, _norm_name(name_raw))
    if best is None:
        return {
            "status": "wrong_medication",
            "can_log": False,
            "scanned": {"name": name_raw, "strength": scanned_strength},
            "message": (
                f"{name_raw} isn't a medication you're tracking. Scan the right bottle, or add this one "
                "as a new prescription if the doctor prescribed it."
            ),
        }

    _, hm, item = best
    med = item.medication
    label = f"{med.name} {med.strength}".strip()
    base = {"medication": {"id": hm.id, "name": med.name, "strength": med.strength}}

    if scanned_strength and normalize_strength(med.strength) != scanned_strength:
        base.update({
            "status": "strength_mismatch",
            "can_log": False,
            "scanned": {"name": name_raw, "strength": scanned_strength},
            "message": (
                f"This bottle is {scanned_strength}, but the prescription you're tracking is {label}. "
                "Don't take it until a pharmacist or doctor checks."
            ),
        })
        return base

    now = _now()
    window_start = now - timedelta(hours=18)
    window_end = now + timedelta(hours=36)
    doses = db.session.scalars(
        select(DoseEvent)
        .where(
            DoseEvent.patient_id == patient.id,
            DoseEvent.prescription_item_id == item.id,
            DoseEvent.scheduled_at >= window_start,
            DoseEvent.scheduled_at <= window_end,
        )
        .order_by(DoseEvent.scheduled_at)
    ).all()

    taken = [d for d in doses if d.status in TAKEN]
    due = [d for d in doses if d.status in OPEN and d.on_time_start <= now <= d.confirm_deadline]
    upcoming = [d for d in doses if d.status == "pending" and d.on_time_start > now]

    base["strength_match"] = True

    if due:
        dose = due[0]
        late = dose.status == "missed"
        base.update({
            "status": "due_now",
            "dose_event_id": dose.id,
            "due_at": _iso(dose.scheduled_at),
            "due_local": _local_hhmm(patient, dose.scheduled_at),
            "window": dose.window_name,
            "late": late,
            "can_log": True,
            "message": (
                f"{label} is past its {dose.window_name} window"
                f"{' (' + str(_local_hhmm(patient, dose.scheduled_at)) + ')' if _local_hhmm(patient, dose.scheduled_at) else ''} — "
                "confirm if it was taken."
                if late
                else f"It's time for {label} ({dose.window_name}"
                     f"{' — ' + str(_local_hhmm(patient, dose.scheduled_at)) if _local_hhmm(patient, dose.scheduled_at) else ''}). "
                     "Confirm after taking it — a scan never records a dose."
            ),
        })
        return base

    if taken:
        last = taken[-1]
        last_at = last.taken_at or last.confirmed_at
        if last_at and (now - last_at) <= timedelta(hours=RECENT_TAKEN_HOURS):
            base.update({
                "status": "already_taken",
                "taken_at": _iso(last_at),
                "taken_local": _local_hhmm(patient, last_at),
                "can_log": False,
                "message": (
                    f"{label} was already logged at {_local_hhmm(patient, last_at)} — not long ago. "
                    "You're all set — don't take another dose."
                ),
            })
            return base

    if upcoming:
        dose = upcoming[0]
        base.update({
            "status": "not_due",
            "due_at": _iso(dose.scheduled_at),
            "due_local": _local_hhmm(patient, dose.scheduled_at),
            "window": dose.window_name,
            "can_log": False,
            "message": (
                f"{label} matches your prescription, but it isn't due yet — next dose at "
                f"{_local_hhmm(patient, dose.scheduled_at) or 'the scheduled time'}."
            ),
        })
        return base

    if taken:
        last = taken[-1]
        last_at = last.taken_at or last.confirmed_at
        base.update({
            "status": "already_taken",
            "taken_at": _iso(last_at),
            "taken_local": _local_hhmm(patient, last_at),
            "can_log": False,
            "message": f"{label} was already logged today at {_local_hhmm(patient, last_at)}. You're all set.",
        })
        return base

    base.update({
        "status": "not_due",
        "can_log": False,
        "message": f"{label} matches your prescription, but no dose is scheduled in the next day.",
    })
    return base
