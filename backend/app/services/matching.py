"""Scan -> prescription item -> dose event (plan.md 5.5 step 1). Never changes dose status."""

import uuid
from datetime import datetime
from decimal import Decimal

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import DoseEvent, Prescription, PrescriptionItem
from app.services.normalize import normalize_name, normalize_strength

NAME_THRESHOLD = 85


def active_items(patient_id: uuid.UUID) -> list[PrescriptionItem]:
    return list(
        db.session.scalars(
            select(PrescriptionItem)
            .join(Prescription)
            .where(Prescription.patient_id == patient_id, Prescription.status == "active")
            .options(selectinload(PrescriptionItem.medication))
        )
    )


def _due_event(item: PrescriptionItem, at: datetime) -> DoseEvent | None:
    return db.session.scalar(
        select(DoseEvent)
        .where(
            DoseEvent.prescription_item_id == item.id,
            DoseEvent.status.in_(("pending", "missed")),
            DoseEvent.on_time_start <= at,
            DoseEvent.confirm_deadline >= at,
        )
        .order_by(func.abs(func.extract("epoch", DoseEvent.scheduled_at - at)))
        .limit(1)
    )


def _next_event(item: PrescriptionItem, at: datetime) -> DoseEvent | None:
    return db.session.scalar(
        select(DoseEvent)
        .where(
            DoseEvent.prescription_item_id == item.id,
            DoseEvent.status == "pending",
            DoseEvent.scheduled_at > at,
        )
        .order_by(DoseEvent.scheduled_at)
        .limit(1)
    )


def match_scan(patient_id: uuid.UUID, drug_name: str, strength, observed_at: datetime) -> dict:
    """Returns {match_status, item, event, next_event, score, candidates}."""
    name = normalize_name(drug_name)
    scan_strength = normalize_strength(strength)
    scored = []
    for item in active_items(patient_id):
        med = item.medication
        score = fuzz.token_set_ratio(name, normalize_name(med.name))
        if score < NAME_THRESHOLD:
            continue
        if scan_strength and med.strength and scan_strength != med.strength:
            continue
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)

    result = {"match_status": "no_match", "item": None, "event": None, "next_event": None, "score": None, "candidates": []}
    if not scored:
        return result

    if len(scored) > 1:
        # Prefer the single candidate that actually has a dose due now.
        due = [(s, it, ev) for s, it in scored if (ev := _due_event(it, observed_at)) is not None]
        if len(due) == 1:
            score, item, event = due[0]
            return {**result, "match_status": "matched", "item": item, "event": event, "score": score}
        result["match_status"] = "ambiguous"
        result["candidates"] = [it for _, it in scored]
        return result

    score, item = scored[0]
    event = _due_event(item, observed_at)
    if event is None:
        return {**result, "match_status": "not_due", "item": item, "score": score, "next_event": _next_event(item, observed_at)}
    return {**result, "match_status": "matched", "item": item, "event": event, "score": score}


def quantity_check(item: PrescriptionItem, quantity: Decimal) -> str:
    if item.dose_quantity is None:
        return "unknown"
    return "ok" if Decimal(quantity) == item.dose_quantity else "mismatch"
