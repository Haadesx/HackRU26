"""Track-tab dose scanner (frontend/docs/api-contract.md, "Dose match").

Identifies the bottle in a photo and compares it with today's schedule. It never records a
dose: the caregiver presses "Rosa took it", which calls POST /medications/{id}/doses with
method "scan" and the returned slot (the normal, re-checked logging path).

- Identity: the fail-closed check in app.hub.verify (name and strength must be read clearly
  and match a tracked prescription exactly). Anything it can't confirm is a 422 with a
  readable sentence, never a guess.
- Schedule: looked up here by medication (not prescription item, so doses from an earlier
  prescription version still count) and limited to the patient's local *today*, the same
  day the Track tab and POST /medications/{id}/doses work with.

Result statuses (UI contract): match | wrong_bottle | already_taken | not_scheduled.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.errors import ApiError
from app.extensions import db
from app.hub import state as hub_state
from app.hub import verify as hub_verify
from app.models import DoseEvent, HubMedication, User
from app.utils.time import get_zone, utcnow

TAKEN = ("taken_on_time", "taken_late")
OPEN = ("pending", "missed")


def _hhmm(patient: User, dt) -> str:
    return dt.astimezone(get_zone(patient.timezone)).strftime("%H:%M")


def _hub_ids(patient: User) -> dict:
    return {
        hm.medication_id: hm.id
        for hm in db.session.scalars(select(HubMedication).where(HubMedication.patient_id == patient.id))
    }


def _tracked_medication_ids(patient: User) -> set:
    """Medications the dashboard tracks right now. Doses of a medication that was stopped (or of the demo seed's old
    prescriptions) can stay open in dose_events, but they are not "due" for the scanner."""
    return {item.medication_id for _hm, item in hub_state.tracked(patient)}


def today_events(patient: User, medication_id=None) -> list[DoseEvent]:
    tz = get_zone(patient.timezone)
    start = datetime.combine(utcnow().astimezone(tz).date(), datetime.min.time(), tzinfo=tz)
    stmt = (
        select(DoseEvent)
        .where(
            DoseEvent.patient_id == patient.id,
            DoseEvent.scheduled_at >= start,
            DoseEvent.scheduled_at < start + timedelta(days=1),
        )
        .order_by(DoseEvent.scheduled_at)
    )
    if medication_id is not None:
        stmt = stmt.where(DoseEvent.medication_id == medication_id)
    tracked = _tracked_medication_ids(patient)
    return [e for e in db.session.scalars(stmt) if e.medication_id in tracked]


def _open_now(events: list[DoseEvent]) -> DoseEvent | None:
    now = utcnow()
    return next((e for e in events if e.status in OPEN and e.on_time_start <= now <= e.confirm_deadline), None)


def due_now(patient: User, exclude_medication_id=None) -> DoseEvent | None:
    """Today's dose that can be taken right now, earliest first (optionally for any *other* medication)."""
    events = [e for e in today_events(patient) if e.medication_id != exclude_medication_id]
    return _open_now(events)


def _expected(patient: User, event: DoseEvent, hub_ids: dict) -> dict:
    return {"medication_id": hub_ids.get(event.medication_id), "name": event.medication.name, "slot": _hhmm(patient, event.scheduled_at)}


def match_dose(patient: User, fields: dict) -> tuple[dict, str | None]:
    """Returns (result, wrong_bottle_event_message_or_None)."""
    verification = hub_verify.scan_verification(patient, SimpleNamespace(fields=fields))
    status = verification["status"]
    if status == "uncertain":
        raise ApiError(422, "UNREADABLE", verification["message"])

    hub_ids = _hub_ids(patient)
    first_name = patient.name.split()[0]

    if status in ("wrong_medication", "strength_mismatch"):
        scanned = verification.get("scanned") or {}
        name = scanned.get("name") or fields.get("name", {}).get("value", "")
        strength = scanned.get("strength") or ""
        expected = due_now(patient)
        if expected is None:
            return {"status": "not_scheduled", "name": name, "strength": strength, "reason": status, "message": verification["message"]}, None
        exp = _expected(patient, expected, hub_ids)
        event_msg = f"{first_name} picked up {f'{name} {strength}'.strip()} when {exp['name']} was due. MedCheck caught it before it was taken."
        return {
            "status": "wrong_bottle", "medication_id": None, "name": name, "strength": strength,
            "expected": exp, "reason": status, "message": verification["message"],
        }, event_msg

    # Identified as a tracked medication with a matching strength.
    med = verification["medication"]  # {"id": hub id, "name", "strength"}
    label = f"{med['name']} {med['strength'] or ''}".strip()
    base = {"medication_id": med["id"], "name": med["name"], "strength": med["strength"] or ""}
    medication_uuid = next((k for k, v in hub_ids.items() if v == med["id"]), None)
    mine = today_events(patient, medication_uuid)
    now = utcnow()

    dose = _open_now(mine)
    if dose is not None:
        late = now > dose.on_time_end
        slot = _hhmm(patient, dose.scheduled_at)
        return {
            **base, "status": "match", "slot": slot, "late": late,
            "message": f"That's {label}, due at {slot}{' (late)' if late else ''}. Confirm only after it's taken.",
        }, None

    other = due_now(patient, exclude_medication_id=medication_uuid)
    if other is not None:
        exp = _expected(patient, other, hub_ids)
        event_msg = f"{first_name} picked up {med['name']} when {exp['name']} was due. MedCheck caught it before it was taken."
        return {
            **base, "status": "wrong_bottle", "expected": exp, "reason": "not_due",
            "message": f"{label} isn't due now. {exp['name']} is due at {exp['slot']}.",
        }, event_msg

    upcoming = next((e for e in mine if e.status == "pending" and e.on_time_start > now), None)
    taken = [e for e in mine if e.status in TAKEN]
    if taken:
        last = taken[-1]
        when = f" Next dose at {_hhmm(patient, upcoming.scheduled_at)}." if upcoming else " No more doses today."
        return {
            **base, "status": "already_taken", "slot": _hhmm(patient, last.scheduled_at), "taken_at": last.taken_at,
            "message": f"{label} was already taken at {_hhmm(patient, last.taken_at)}. Taking it again would be a double dose.{when}",
        }, None

    if upcoming is not None:
        msg = f"{label} isn't due yet. Next dose at {_hhmm(patient, upcoming.scheduled_at)} (you can log it from {_hhmm(patient, upcoming.on_time_start)})."
    else:
        msg = f"No more {label} doses are scheduled today."
    return {**base, "status": "not_scheduled", "message": msg}, None
