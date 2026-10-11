"""Scan-vs-prescription verification for the dashboard.

Turns a scan's read fields into a caregiver-facing safety result by comparing against the
patient's tracked medications and today's dose events. Read-only: it never records a dose.

Fail-closed rule: a positive identification (``due_now`` / ``not_due`` / ``already_taken``)
requires *readable* evidence for both identity and strength — the name field must be
``filled``, its normalized text must match a tracked medication exactly, and the strength
field must be ``filled``, parseable, and match that same prescription. Fuzzy name
similarity only produces a candidate; it is never treated as proof. Missing, unsure, or
ambiguous evidence returns ``uncertain`` with ``can_log`` false.

Statuses: ``uncertain`` · ``wrong_medication`` · ``strength_mismatch`` · ``due_now`` ·
``already_taken`` · ``not_due``. Exactly one is returned; ``can_log`` is true only for
``due_now`` (the UI must still require an explicit confirm action, and the backend
re-checks eligibility when the dose is actually logged).
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
NAME_MATCH_MIN = 88  # rapidfuzz ratio: candidate floor, not an identity proof
RECENT_TAKEN_HOURS = 6  # wording threshold for "not long ago"


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


def _local(patient, value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(get_zone(patient.timezone))


def _local_hhmm(patient, value: Optional[datetime]) -> Optional[str]:
    local = _local(patient, value)
    return local.strftime("%H:%M") if local else None


def _when_text(patient, value: Optional[datetime], now: datetime) -> Optional[str]:
    """Caregiver wording for a time: 'today at 08:00', 'tomorrow at 08:00', 'Monday at 08:00'."""
    local = _local(patient, value)
    if local is None:
        return None
    today = (now if now.tzinfo else now.replace(tzinfo=timezone.utc)).astimezone(get_zone(patient.timezone)).date()
    delta = (local.date() - today).days
    if delta == 0:
        return f"today at {local:%H:%M}"
    if delta == 1:
        return f"tomorrow at {local:%H:%M}"
    return f"{local:%A} at {local:%H:%M}"


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


def _uncertain(message: str, scanned: Optional[dict] = None, **extra) -> dict:
    out = {"status": "uncertain", "can_log": False, "message": message}
    if scanned is not None:
        out["scanned"] = scanned
    out.update(extra)
    return out


def _name_candidates(patient, name: str):
    """Tracked items whose name matches (exact-normalized first, then fuzzy >= floor).

    Returns a list of ``(score, exact, hm, item)`` sorted exact-first then by score.
    A single fuzzy hit is still only a candidate — callers must not call it a match.
    """
    out = []
    for hm, item in hub_state.tracked(patient):
        med_name = _norm_name(item.medication.name)
        exact = bool(med_name) and med_name == name
        score = 100.0 if exact else float(fuzz.ratio(med_name, name))
        if exact or score >= NAME_MATCH_MIN:
            out.append((score, exact, hm, item))
    out.sort(key=lambda c: (c[1], c[0]), reverse=True)
    return out


def scan_verification(patient, scan) -> Optional[dict]:
    """Verification block for a scan (JSON-safe). ``None`` when the scan has no read name."""
    name_raw, name_state, strength_text, strength_state = _scan_text(scan)

    if not name_raw or name_state == "missing":
        return _uncertain("We couldn't read the medication name clearly. Take another photo, or check the label and add the details by hand.")

    if name_state != "filled":
        # A low-confidence reading is a lead, not an identity.
        return _uncertain(
            f"We read “{name_raw}”, but not clearly enough to be sure which medication this is. "
            "Take another photo, or check the label against the bottle.",
            {"name": name_raw, "strength": None},
        )

    scanned_strength = normalize_strength(strength_text) if strength_text else None
    if not scanned_strength or strength_state != "filled":
        readable = f" We did read “{scanned_strength}” there." if scanned_strength else ""
        return _uncertain(
            f"We read the name ({name_raw}) but not the strength clearly.{readable} "
            "A strength we can't read can't be checked against the prescription — take another photo, "
            "or compare the bottle with the label by hand.",
            {"name": name_raw, "strength": scanned_strength},
        )

    candidates = _name_candidates(patient, _norm_name(name_raw))
    if not candidates:
        return {
            "status": "wrong_medication",
            "can_log": False,
            "scanned": {"name": name_raw, "strength": scanned_strength},
            "message": (
                f"{name_raw} isn't a medication you're tracking. Scan the right bottle, or add this one "
                "as a new prescription if the doctor prescribed it."
            ),
        }

    exact = [c for c in candidates if c[1]]
    if not exact:
        # Fuzzy-only: possible match, never proof.
        options = ", ".join(dict.fromkeys(f"{c[3].medication.name} {c[3].medication.strength}" for c in candidates))
        return _uncertain(
            f"We read “{name_raw}”, which looks like {options} — but the wording doesn't match your tracker "
            "exactly. Check the bottle against the label and confirm by hand.",
            {"name": name_raw, "strength": scanned_strength},
        )

    strength_matches = [c for c in exact if normalize_strength(c[3].medication.strength) == scanned_strength]
    if not strength_matches:
        tracked = list(dict.fromkeys(f"{c[3].medication.name} {c[3].medication.strength}".strip() for c in exact))
        if len(tracked) == 1:
            message = (
                f"This bottle is {scanned_strength}, but the prescription you're tracking is {tracked[0]}. "
                "Don't take it until a pharmacist or doctor checks."
            )
        else:
            message = (
                f"This bottle is {scanned_strength}, which doesn't match any tracked strength for "
                f"{exact[0][3].medication.name} ({', '.join(tracked)}). "
                "Don't take it until a pharmacist or doctor checks."
            )
        return {
            "status": "strength_mismatch",
            "can_log": False,
            "scanned": {"name": name_raw, "strength": scanned_strength},
            "message": message,
        }

    if len(strength_matches) > 1:
        # Same name and strength tracked twice: the evidence cannot pick one.
        return _uncertain(
            f"Your records have more than one {name_raw} {scanned_strength} prescription, so we can't tell "
            "which one this bottle belongs to. Ask a pharmacist or caregiver to check before taking it.",
            {"name": name_raw, "strength": scanned_strength},
        )

    _, _, hm, item = strength_matches[0]
    med = item.medication
    label = f"{med.name} {med.strength}".strip()
    base = {
        "medication": {"id": hm.id, "name": med.name, "strength": med.strength},
        "strength_match": True,
        "matched": {"name": "exact", "strength": "exact"},
    }

    now = _now()
    tz = get_zone(patient.timezone)
    today = now.astimezone(tz).date()
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
    pending = [d for d in doses if d.status == "pending" and d.on_time_start > now]
    pending_today = [d for d in pending if d.on_time_start.astimezone(tz).date() == today]

    if due:
        dose = due[0]
        late = dose.status == "missed"
        at = _local_hhmm(patient, dose.scheduled_at)
        base.update({
            "status": "due_now",
            "dose_event_id": dose.id,
            "due_at": _iso(dose.scheduled_at),
            "due_local": at,
            "window": dose.window_name,
            "late": late,
            "can_log": True,
            "message": (
                f"{label} is past its {dose.window_name} window{f' ({at})' if at else ''} — confirm if it was taken."
                if late
                else f"It's time for {label} ({dose.window_name}{f' — {at}' if at else ''}). "
                     "Confirm after taking it — a scan never records a dose."
            ),
        })
        return base

    if pending_today:
        # A later dose today must never be hidden by an earlier confirmed dose.
        dose = pending_today[0]
        at = _local_hhmm(patient, dose.scheduled_at)
        already = ""
        if taken:
            last = taken[-1]
            last_at = last.taken_at or last.confirmed_at
            if last_at and last_at.astimezone(tz).date() == today:
                already = f" The {last.window_name} dose was already logged at {_local_hhmm(patient, last_at)}."
        base.update({
            "status": "not_due",
            "due_at": _iso(dose.scheduled_at),
            "due_local": at,
            "window": dose.window_name,
            "can_log": False,
            "message": (
                f"{label} matches your prescription.{already} It isn't due yet — next dose today at "
                f"{at or 'the scheduled time'}."
            ),
        })
        return base

    if taken:
        last = taken[-1]
        last_at = last.taken_at or last.confirmed_at
        recent = bool(last_at) and (now - last_at) <= timedelta(hours=RECENT_TAKEN_HOURS)
        logged_word = "was already logged today" if last_at and last_at.astimezone(tz).date() == today else "was last logged"
        next_note = f" Next dose {_when_text(patient, pending[0].scheduled_at, now)}." if pending else ""
        base.update({
            "status": "already_taken",
            "taken_at": _iso(last_at),
            "taken_local": _local_hhmm(patient, last_at),
            "can_log": False,
            "message": (
                f"{label} {logged_word} at {_local_hhmm(patient, last_at)}"
                + (" — not long ago. You're all set — don't take another dose." if recent else ".")
                + next_note
            ),
        })
        return base

    if pending:
        dose = pending[0]
        base.update({
            "status": "not_due",
            "due_at": _iso(dose.scheduled_at),
            "due_local": _local_hhmm(patient, dose.scheduled_at),
            "window": dose.window_name,
            "can_log": False,
            "message": (
                f"{label} matches your prescription, but it isn't due yet — next dose "
                f"{_when_text(patient, dose.scheduled_at, now) or 'at the scheduled time'}."
            ),
        })
        return base

    base.update({
        "status": "not_due",
        "can_log": False,
        "message": f"{label} matches your prescription, but no dose is scheduled in the next day.",
    })
    return base
