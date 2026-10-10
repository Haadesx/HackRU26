"""Inventory and refills (plan.md 5.9, 5.10). Low-stock thresholds live in the front end."""

import uuid
from decimal import Decimal

from flask_jwt_extended import current_user, jwt_required
from flask_smorest import Blueprint
from sqlalchemy import select

from app import serializers
from app.errors import bad_request, conflict, not_found
from app.extensions import db
from app.models import (
    InventoryTransaction,
    Medication,
    MedicationInventory,
    Prescription,
    PrescriptionItem,
    RefillRequest,
    User,
)
from app.schemas import InventoryUpdateSchema, RefillCreateSchema, RefillFulfillSchema, RefillUpdateSchema
from app.services import inventory as inv_service
from app.services import notifications
from app.services.permissions import require_patient_access
from app.utils.time import get_zone, utcnow

blp = Blueprint("inventory", __name__, description="Inventory and refills")

_PERIOD_DAYS = {"daily": 1, "every_other_day": 2, "weekly": 7}


def _daily_usage(patient_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    usage: dict[uuid.UUID, Decimal] = {}
    items = db.session.scalars(
        select(PrescriptionItem)
        .join(Prescription)
        .where(Prescription.patient_id == patient_id, Prescription.status == "active")
    ).all()
    for item in items:
        s = item.schedule
        if s is None or not s.active or item.dose_quantity is None:
            continue
        per_day = item.dose_quantity * len(s.times) / _PERIOD_DAYS[s.frequency]
        usage[item.medication_id] = usage.get(item.medication_id, Decimal(0)) + per_day
    return usage


def _estimate(inv: MedicationInventory, usage: dict) -> float | None:
    per_day = usage.get(inv.medication_id)
    if inv.quantity_remaining is None or not per_day:
        return None
    return round(float(inv.quantity_remaining / per_day), 1)


@blp.route("/patients/<uuid:patient_id>/inventory")
@jwt_required()
@blp.response(200)
def list_inventory(patient_id: uuid.UUID):
    patient = require_patient_access(patient_id)
    usage = _daily_usage(patient.id)
    rows = db.session.scalars(
        select(MedicationInventory)
        .join(Medication)
        .where(MedicationInventory.patient_id == patient.id)
        .order_by(Medication.name)
    ).all()
    return {"inventory": [serializers.inventory(r, _estimate(r, usage)) for r in rows]}


@blp.route("/patients/<uuid:patient_id>/inventory/<uuid:medication_id>", methods=["PUT"])
@jwt_required()
@blp.arguments(InventoryUpdateSchema)
@blp.response(200)
def set_inventory(data, patient_id: uuid.UUID, medication_id: uuid.UUID):
    """Initialize or correct stock. Writes a manual_adjustment transaction for the difference."""
    patient = require_patient_access(patient_id, write=True)
    if db.session.get(Medication, medication_id) is None:
        raise not_found("Medication")
    inv = inv_service.get_inventory(patient.id, medication_id)
    if inv is None:
        if not data.get("quantity_unit"):
            raise bad_request("UNIT_REQUIRED", "quantity_unit is required when stock is first recorded.")
        inv = inv_service.ensure_inventory(patient.id, medication_id, data["quantity_unit"])
    elif data.get("quantity_unit"):
        inv.quantity_unit = data["quantity_unit"]
    inv_service.set_quantity(inv, data["quantity_remaining"], created_by=current_user.id, note=data.get("note"))
    db.session.commit()
    return serializers.inventory(inv, _estimate(inv, _daily_usage(patient.id)))


@blp.route("/patients/<uuid:patient_id>/inventory/<uuid:medication_id>/transactions")
@jwt_required()
@blp.response(200)
def list_transactions(patient_id: uuid.UUID, medication_id: uuid.UUID):
    patient = require_patient_access(patient_id)
    rows = db.session.scalars(
        select(InventoryTransaction)
        .where(InventoryTransaction.patient_id == patient.id, InventoryTransaction.medication_id == medication_id)
        .order_by(InventoryTransaction.created_at.desc())
        .limit(500)
    ).all()
    return {"transactions": [serializers.inventory_transaction(t) for t in rows]}


# ---------- refills ----------


def _notify_refill(refill: RefillRequest, title: str, body: str) -> None:
    recipients = [refill.patient_id] + [c.id for c in notifications.alert_caregivers(refill.patient_id)]
    for rid in recipients:
        notifications.create_reminder(
            patient_id=refill.patient_id,
            recipient_id=rid,
            kind="refill_update",
            title=title,
            body=body,
            refill_request_id=refill.id,
        )
    if len(recipients) > 1:
        refill.caregiver_notified_at = utcnow()


def _appointment_text(refill: RefillRequest) -> str:
    tz = db.session.get(User, refill.patient_id).timezone
    parts = []
    if refill.appointment_at:
        local = refill.appointment_at.astimezone(get_zone(tz))
        parts.append(f"on {local.strftime('%b %d')} at {local.strftime('%H:%M')}")
    if refill.pharmacy_or_provider:
        parts.append(f"with {refill.pharmacy_or_provider}")
    return " ".join(parts)


def _load_refill(refill_id: uuid.UUID) -> RefillRequest:
    refill = db.session.get(RefillRequest, refill_id)
    if refill is None:
        raise not_found("Refill")
    require_patient_access(refill.patient_id, write=True)
    return refill


@blp.route("/patients/<uuid:patient_id>/refills", methods=["POST"])
@jwt_required()
@blp.arguments(RefillCreateSchema)
@blp.response(201)
def create_refill(data, patient_id: uuid.UUID):
    patient = require_patient_access(patient_id, write=True)
    item = db.session.get(PrescriptionItem, data["prescription_item_id"])
    if item is None or item.prescription.patient_id != patient.id:
        raise not_found("Prescription item")
    refill = RefillRequest(
        patient_id=patient.id,
        prescription_item_id=item.id,
        requested_by=current_user.id,
        appointment_at=data.get("appointment_at"),
        pharmacy_or_provider=data.get("pharmacy_or_provider"),
        status="scheduled" if data.get("appointment_at") else "requested",
    )
    db.session.add(refill)
    db.session.flush()
    if refill.status == "scheduled":
        label = notifications.med_label(item)
        _notify_refill(refill, f"Refill scheduled: {label}", f"Refill for {label} {_appointment_text(refill)}.")
    db.session.commit()
    return serializers.refill(refill)


@blp.route("/patients/<uuid:patient_id>/refills")
@jwt_required()
@blp.response(200)
def list_refills(patient_id: uuid.UUID):
    patient = require_patient_access(patient_id)
    rows = db.session.scalars(
        select(RefillRequest).where(RefillRequest.patient_id == patient.id).order_by(RefillRequest.created_at.desc())
    ).all()
    return {"refills": [serializers.refill(r) for r in rows]}


@blp.route("/refills/<uuid:refill_id>", methods=["PATCH"])
@jwt_required()
@blp.arguments(RefillUpdateSchema)
@blp.response(200)
def update_refill(data, refill_id: uuid.UUID):
    """Set appointment time and/or pharmacy. Setting appointment_at moves the refill to `scheduled`."""
    refill = _load_refill(refill_id)
    if refill.status not in ("requested", "scheduled"):
        raise conflict("REFILL_CLOSED", f"Refill is already {refill.status}.")
    for field, value in data.items():
        setattr(refill, field, value)
    if refill.appointment_at:
        refill.status = "scheduled"
        label = notifications.med_label(refill.item)
        _notify_refill(refill, f"Refill scheduled: {label}", f"Refill for {label} {_appointment_text(refill)}.")
    db.session.commit()
    return serializers.refill(refill)


@blp.route("/refills/<uuid:refill_id>/fulfill", methods=["POST"])
@jwt_required()
@blp.arguments(RefillFulfillSchema)
@blp.response(200)
def fulfill_refill(data, refill_id: uuid.UUID):
    """Mark picked up. Adds quantity_added to stock via a refill transaction."""
    refill = _load_refill(refill_id)
    if refill.status not in ("requested", "scheduled"):
        raise conflict("REFILL_CLOSED", f"Refill is already {refill.status}.")
    item = refill.item
    refill.status = "fulfilled"
    refill.quantity_added = data["quantity_added"]
    refill.fulfilled_at = data.get("fulfilled_at") or utcnow()
    db.session.flush()
    inv_service.ensure_inventory(refill.patient_id, item.medication_id, item.dose_unit or "unit")
    inv_service.apply_transaction(
        refill.patient_id,
        item.medication_id,
        data["quantity_added"],
        "refill",
        refill_request_id=refill.id,
        created_by=current_user.id,
        initialize_if_unknown=True,
    )
    label = notifications.med_label(item)
    _notify_refill(refill, f"Refill picked up: {label}", f"{notifications.qty_text(refill.quantity_added, item.dose_unit)} of {label} added to stock.")
    db.session.commit()
    inv = inv_service.get_inventory(refill.patient_id, item.medication_id)
    return {"refill": serializers.refill(refill), "inventory": serializers.inventory(inv, _estimate(inv, _daily_usage(refill.patient_id)))}


@blp.route("/refills/<uuid:refill_id>/cancel", methods=["POST"])
@jwt_required()
@blp.response(200)
def cancel_refill(refill_id: uuid.UUID):
    refill = _load_refill(refill_id)
    if refill.status not in ("requested", "scheduled"):
        raise conflict("REFILL_CLOSED", f"Refill is already {refill.status}.")
    refill.status = "cancelled"
    db.session.commit()
    return serializers.refill(refill)
