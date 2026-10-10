"""Dose events, scans, tap-to-confirm, skip (plan.md 5.5)."""

import json
import uuid
from datetime import datetime, time, timedelta

from flask import current_app
from flask_jwt_extended import current_user, jwt_required
from flask_smorest import Blueprint
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import serializers
from app.errors import bad_request, forbidden, not_found
from app.extensions import db
from app.models import DoseEvent, PrescriptionItem, VisionObservation
from app.schemas import ConfirmSchema, DoseRangeQuerySchema, ScanSchema
from app.services import doses as dose_service
from app.services import matching
from app.services.adherence import timing_label
from app.services.normalize import normalize_strength
from app.services.permissions import require_patient_access, require_patient_self
from app.utils.time import ensure_utc, get_zone, utcnow

blp = Blueprint("doses", __name__, description="Doses, scans, confirm/skip")

MAX_RANGE = timedelta(days=31)
FUTURE_SKEW = timedelta(minutes=5)


@blp.route("/patients/<uuid:patient_id>/doses")
@jwt_required()
@blp.arguments(DoseRangeQuerySchema, location="query")
@blp.response(200)
def list_doses(args, patient_id: uuid.UUID):
    """Dose events in [from, to). Defaults to the patient's local today."""
    patient = require_patient_access(patient_id)
    tz = get_zone(patient.timezone)
    today = utcnow().astimezone(tz).date()
    start = ensure_utc(args["start"]) if args.get("start") else datetime.combine(today, time(0), tzinfo=tz)
    end = ensure_utc(args["end"]) if args.get("end") else start + timedelta(days=1)
    if end <= start or end - start > MAX_RANGE:
        raise bad_request("INVALID_RANGE", "'to' must be after 'from' and within 31 days.")
    stmt = (
        select(DoseEvent)
        .where(DoseEvent.patient_id == patient.id, DoseEvent.scheduled_at >= start, DoseEvent.scheduled_at < end)
        .order_by(DoseEvent.scheduled_at)
    )
    if args.get("status"):
        stmt = stmt.where(DoseEvent.status.in_(args["status"].split(",")))
    events = db.session.scalars(stmt).all()
    return {"from": start, "to": end, "timezone": patient.timezone, "doses": [serializers.dose_event(e) for e in events]}


@blp.route("/doses/<uuid:dose_id>")
@jwt_required()
@blp.response(200)
def get_dose(dose_id: uuid.UUID):
    event = db.session.get(DoseEvent, dose_id)
    if event is None:
        raise not_found("Dose")
    require_patient_access(event.patient_id)
    return serializers.dose_event(event)


def _scan_response(obs: VisionObservation, replay: bool) -> dict:
    item = None
    event = db.session.get(DoseEvent, obs.dose_event_id) if obs.dose_event_id else None
    if event is not None:
        item = event.item
    elif obs.medication_id is not None:
        item = next(
            (i for i in matching.active_items(obs.patient_id) if i.medication_id == obs.medication_id), None
        )
    result = obs.payload.get("result", {})
    response = {
        "match_status": obs.match_status,
        "observation_event_id": obs.event_id,
        "observed_at": obs.observed_at,
        "replayed": replay,
        "medication": serializers.medication(item.medication) if item else None,
        "prescription_item_id": item.id if item else None,
        "dose_event": serializers.dose_event(event) if event else None,
        "timing": timing_label(event, obs.observed_at) if event and event.status in ("pending", "missed") else None,
        "quantity_check": matching.quantity_check(item, obs.quantity) if item else None,
        "scanned_quantity": obs.quantity,
        "expected_quantity": item.dose_quantity if item else None,
        "next_dose": result.get("next_dose"),
        "candidates": result.get("candidates", []),
        "safety": {
            "ingestion_not_inferred": True,
            "message": "A scan does not record a dose. Tap confirm after taking it.",
        },
    }
    return response


@blp.route("/scans", methods=["POST"])
@jwt_required()
@blp.arguments(ScanSchema)
@blp.response(200)
def ingest_scan(data):
    """Record a scan and match it to a due dose. Idempotent on event_id. Does not change dose status."""
    user = require_patient_self()
    if data["user_id"] != user.id:
        raise forbidden("user_id does not match the signed-in user.")
    observed_at = ensure_utc(data["timestamp"])
    if observed_at > utcnow() + FUTURE_SKEW:
        raise bad_request("TIMESTAMP_IN_FUTURE", "timestamp is in the future. Send the scan time in UTC.")

    existing = db.session.scalar(select(VisionObservation).where(VisionObservation.event_id == data["event_id"]))
    if existing is not None:
        if existing.patient_id != user.id:
            raise forbidden("event_id already used by another account.")
        return _scan_response(existing, replay=True)

    match = matching.match_scan(user.id, data["drug_name"], data.get("strength"), observed_at)
    item: PrescriptionItem | None = match["item"]
    event: DoseEvent | None = match["event"]
    extra = {
        "candidates": [
            {"prescription_item_id": str(i.id), **serializers.medication(i.medication)} for i in match["candidates"]
        ],
        "next_dose": (
            {"id": str(match["next_event"].id), "scheduled_at": match["next_event"].scheduled_at.isoformat()}
            if match["next_event"]
            else None
        ),
    }
    # Round-trip through the app JSON provider so UUIDs/Decimals/datetimes are JSONB-safe.
    payload = json.loads(current_app.json.dumps({"request": data, "result": extra}))
    stmt = (
        insert(VisionObservation)
        .values(
            observed_at=observed_at,
            event_id=data["event_id"],
            patient_id=user.id,
            drug_name=data["drug_name"].strip(),
            strength=normalize_strength(data.get("strength")),
            quantity=data["quantity"],
            medication_id=item.medication_id if item else None,
            dose_event_id=event.id if event else None,
            match_status=match["match_status"],
            match_score=match["score"],
            payload=payload,
            received_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["event_id", "observed_at"])
    )
    db.session.execute(stmt)
    db.session.commit()
    obs = db.session.scalar(select(VisionObservation).where(VisionObservation.event_id == data["event_id"]))
    return _scan_response(obs, replay=False)


@blp.route("/doses/<uuid:dose_id>/confirm", methods=["POST"])
@jwt_required()
@blp.arguments(ConfirmSchema)
@blp.response(200)
def confirm_dose(data, dose_id: uuid.UUID):
    """Tap to confirm (patient only). Works for pending doses and for missed doses until confirm_deadline."""
    event = dose_service.lock_event(dose_id)
    require_patient_access(event.patient_id, write=True)
    result = dose_service.confirm(
        event,
        user_id=current_user.id,
        observation_event_id=data.get("observation_event_id"),
        quantity_taken=data.get("quantity_taken"),
    )
    db.session.commit()
    return {"dose": serializers.dose_event(db.session.get(DoseEvent, dose_id)), **result}


@blp.route("/doses/<uuid:dose_id>/skip", methods=["POST"])
@jwt_required()
@blp.response(200)
def skip_dose(dose_id: uuid.UUID):
    event = dose_service.lock_event(dose_id)
    require_patient_access(event.patient_id, write=True)
    dose_service.skip(event)
    db.session.commit()
    return {"dose": serializers.dose_event(db.session.get(DoseEvent, dose_id))}
