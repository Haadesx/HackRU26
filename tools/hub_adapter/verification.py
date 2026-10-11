"""Scan-vs-prescription verification for the fallback hub adapter.

Mirrors `backend/app/hub/verify.py` so `HUB_MODE=demo` (and the backend-mode
fallback) behaves like the real `/hub`. Exactly one of six statuses is returned:

``uncertain`` · ``wrong_medication`` · ``strength_mismatch`` · ``already_taken`` ·
``due_now`` · ``not_due``

``can_log`` is true only for ``due_now``. Verification is read-only: it never
records a dose. Fuzzy name matching uses stdlib ``difflib`` with the same 0.88
threshold as the backend (rapidfuzz is not installed in the demo environment).
"""
from __future__ import annotations

import difflib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

NAME_MATCH_MIN = 0.88  # same threshold as backend rapidfuzz ratio
RECENT_TAKEN_HOURS = 6  # a dose confirmed this recently means "don't take another"
DUE_WINDOW_MINUTES = 30  # scheduled time within +/- this window is "due now"

UNCERTAIN_MESSAGE = (
    "We couldn't read the medication name clearly. Take another photo, or check the label."
)

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


def _now() -> datetime:
    """Local tz-aware clock; tests may monkeypatch this."""
    return datetime.now().astimezone()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hhmm(value: Optional[datetime], tz) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(tz).strftime("%H:%M")


def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _norm_strength(value: Any) -> str:
    text = " ".join(str(value or "").strip().casefold().split())
    if not text:
        return ""
    return re.sub(r"(\d)([a-z])", r"\1 \2", text)


def _scan_name(scan: Dict[str, Any]) -> Tuple[str, str]:
    field = (scan.get("fields") or {}).get("name") or {}
    return str(field.get("value") or "").strip(), str(field.get("state") or "missing")


def _scan_strength(scan: Dict[str, Any]) -> str:
    field = (scan.get("fields") or {}).get("strength") or {}
    return _norm_strength(field.get("value"))


def _match_tracked(medications: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """Best tracked medication by name: exact casefold first, then difflib >= 0.88."""
    best: Optional[Tuple[Tuple[float, int], Dict[str, Any]]] = None
    for med in medications:
        med_name = _norm_name(med.get("name"))
        if not med_name:
            continue
        exact = med_name == name
        ratio = 1.0 if exact else difflib.SequenceMatcher(a=med_name, b=name).ratio()
        if ratio < NAME_MATCH_MIN:
            continue
        rank = (ratio, 1 if exact else 0)
        if best is None or rank > best[0]:
            best = (rank, med)
    return best[1] if best is not None else None


def _taken_at(dose: Dict[str, Any]) -> Optional[datetime]:
    for key in ("taken_at", "confirmed_at"):
        raw = dose.get(key)
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _scheduled_occurrences(med: Dict[str, Any], now: datetime) -> List[datetime]:
    """Today's and tomorrow's naive HH:MM schedule times, anchored to `now`'s tz."""
    occurrences: List[datetime] = []
    for raw in med.get("schedule_times") or []:
        match = _HHMM.match(str(raw).strip())
        if not match:
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            continue
        for day_offset in (0, 1):
            base = (now + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            occurrences.append(base)
    return sorted(occurrences)


def scan_verification(
    scan: Dict[str, Any],
    medications: List[Dict[str, Any]],
    doses: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Verification block for one scan. Never returns None; never records a dose."""
    current = now or _now()
    tz = current.tzinfo or timezone.utc

    name_raw, name_state = _scan_name(scan)
    if not name_raw or name_state == "missing":
        return {"status": "uncertain", "can_log": False, "message": UNCERTAIN_MESSAGE}

    scanned_strength = _scan_strength(scan)
    med = _match_tracked(medications, _norm_name(name_raw))
    if med is None:
        return {
            "status": "wrong_medication",
            "can_log": False,
            "scanned": {"name": name_raw, "strength": scanned_strength or None},
            "message": (
                f"{name_raw} isn't a medication you're tracking. Scan the right bottle, or add this one "
                "as a new prescription if the doctor prescribed it."
            ),
        }

    label = f"{med.get('name')} {med.get('strength')}".strip()
    base: Dict[str, Any] = {
        "medication": {"id": med.get("id"), "name": med.get("name"), "strength": med.get("strength")}
    }

    tracked_strength = _norm_strength(med.get("strength"))
    if scanned_strength and tracked_strength and scanned_strength != tracked_strength:
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

    base["strength_match"] = True
    med_id = str(med.get("id"))
    taken = sorted(
        ((stamp, dose) for stamp, dose in ((_taken_at(d), d) for d in doses if str(d.get("medication_id")) == med_id) if stamp is not None),
        key=lambda pair: pair[0],
    )

    recent = [(stamp, dose) for stamp, dose in taken if (current - stamp) <= timedelta(hours=RECENT_TAKEN_HOURS)]
    if recent:
        last_at = recent[-1][0]
        base.update({
            "status": "already_taken",
            "taken_at": _iso(last_at),
            "taken_local": _hhmm(last_at, tz),
            "can_log": False,
            "message": (
                f"{label} was already logged at {_hhmm(last_at, tz)} — not long ago. "
                "You're all set — don't take another dose."
            ),
        })
        return base

    occurrences = _scheduled_occurrences(med, current)
    due = [when for when in occurrences if abs((when - current).total_seconds()) <= DUE_WINDOW_MINUTES * 60]
    if due:
        when = due[0]
        base.update({
            "status": "due_now",
            "due_at": _iso(when),
            "due_local": _hhmm(when, tz),
            "window": "scheduled",
            "late": False,
            "can_log": True,
            "message": (
                f"It's time for {label} ({_hhmm(when, tz)}). "
                "Confirm after taking it — a scan never records a dose."
            ),
        })
        return base

    upcoming = [when for when in occurrences if when > current]
    if upcoming:
        when = upcoming[0]
        base.update({
            "status": "not_due",
            "due_at": _iso(when),
            "due_local": _hhmm(when, tz),
            "window": "scheduled",
            "can_log": False,
            "message": (
                f"{label} matches your prescription, but it isn't due yet — next dose at {_hhmm(when, tz)}."
            ),
        })
        return base

    if taken:
        last_at = taken[-1][0]
        base.update({
            "status": "already_taken",
            "taken_at": _iso(last_at),
            "taken_local": _hhmm(last_at, tz),
            "can_log": False,
            "message": f"{label} was already logged today at {_hhmm(last_at, tz)}. You're all set.",
        })
        return base

    base.update({
        "status": "not_due",
        "can_log": False,
        "message": f"{label} matches your prescription, but no dose is scheduled in the next day.",
    })
    return base
