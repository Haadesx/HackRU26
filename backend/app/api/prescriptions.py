"""Prescriptions (draft -> active), schedules, and dose windows."""

import uuid

from flask_jwt_extended import current_user, jwt_required
from flask_smorest import Blueprint
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app import serializers
from app.errors import bad_request, conflict, not_found
from app.extensions import db
from app.models import DoseScheduleTime, DoseWindow, Prescription, PrescriptionItem
from app.schemas import (
    ActivateSchema,
    CreatePrescriptionSchema,
    ScheduleSchema,
    UpdatePrescriptionSchema,
    WindowCreateSchema,
    WindowUpdateSchema,
)
from app.services import prescriptions as rx_service
from app.services import scheduling
from app.services.permissions import require_patient_access

blp = Blueprint("prescriptions", __name__, description="Prescriptions, schedules, dose windows")


def _load_rx(rx_id: uuid.UUID, write: bool) -> Prescription:
    rx = db.session.get(Prescription, rx_id)
    if rx is None:
        raise not_found("Prescription")
    require_patient_access(rx.patient_id, write=write)
    return rx


# ---------- prescriptions ----------


@blp.route("/patients/<uuid:patient_id>/prescriptions", methods=["POST"])
@jwt_required()
@blp.arguments(CreatePrescriptionSchema)
@blp.response(201)
def create_prescription(data, patient_id: uuid.UUID):
    """Create a draft from label data. Each item is looked up in OpenFDA; see items[].verification."""
    patient = require_patient_access(patient_id, write=True)
    rx, verification = rx_service.create_draft(patient, data)
    db.session.commit()
    return serializers.prescription(rx, verification)


@blp.route("/patients/<uuid:patient_id>/prescriptions")
@jwt_required()
@blp.response(200)
def list_prescriptions(patient_id: uuid.UUID):
    patient = require_patient_access(patient_id)
    rows = db.session.scalars(
        select(Prescription).where(Prescription.patient_id == patient.id).order_by(Prescription.version.desc())
    ).all()
    return {"prescriptions": [serializers.prescription_summary(rx) for rx in rows]}


@blp.route("/patients/<uuid:patient_id>/prescriptions/active")
@jwt_required()
@blp.response(200)
def active_prescription(patient_id: uuid.UUID):
    patient = require_patient_access(patient_id)
    rx = db.session.scalar(
        select(Prescription).where(Prescription.patient_id == patient.id, Prescription.status == "active")
    )
    if rx is None:
        raise not_found("Active prescription")
    return serializers.prescription(rx)


@blp.route("/prescriptions/<uuid:rx_id>")
@jwt_required()
@blp.response(200)
def get_prescription(rx_id: uuid.UUID):
    return serializers.prescription(_load_rx(rx_id, write=False))


@blp.route("/prescriptions/<uuid:rx_id>", methods=["PATCH"])
@jwt_required()
@blp.arguments(UpdatePrescriptionSchema)
@blp.response(200)
def update_prescription(data, rx_id: uuid.UUID):
    """Edit a draft: items with `id` are updated, items without `id` are added, remove_item_ids are deleted."""
    rx = _load_rx(rx_id, write=True)
    verification = rx_service.update_draft(rx, data)
    db.session.commit()
    return serializers.prescription(rx, verification)


@blp.route("/prescriptions/<uuid:rx_id>/activate", methods=["POST"])
@jwt_required()
@blp.arguments(ActivateSchema)
@blp.response(200)
def activate_prescription(data, rx_id: uuid.UUID):
    """Validate, supersede the previous active version, create inventory rows, and generate doses."""
    rx = _load_rx(rx_id, write=True)
    result = rx_service.activate(rx, user_id=current_user.id, initialize_inventory=data["initialize_inventory"])
    db.session.commit()
    rx = db.session.get(Prescription, rx_id)
    return {"prescription": serializers.prescription(rx), **result}


@blp.route("/prescriptions/<uuid:rx_id>/revise", methods=["POST"])
@jwt_required()
@blp.response(201)
def revise_prescription(rx_id: uuid.UUID):
    """Copy an active or superseded prescription (items + schedules) into a new draft version."""
    rx = _load_rx(rx_id, write=True)
    draft = rx_service.revise(rx)
    db.session.commit()
    return serializers.prescription(draft)


@blp.route("/prescription-items/<uuid:item_id>/schedule", methods=["PUT"])
@jwt_required()
@blp.arguments(ScheduleSchema)
@blp.response(200)
def put_schedule(data, item_id: uuid.UUID):
    """Set the schedule for a draft item. Each time references a window by id or kind."""
    item = db.session.get(PrescriptionItem, item_id)
    if item is None:
        raise not_found("Prescription item")
    require_patient_access(item.prescription.patient_id, write=True)
    rx_service.set_schedule(item, data)
    db.session.commit()
    return serializers.prescription_item(db.session.get(PrescriptionItem, item_id))


# ---------- dose windows ----------


@blp.route("/patients/<uuid:patient_id>/dose-windows")
@jwt_required()
@blp.response(200)
def list_windows(patient_id: uuid.UUID):
    patient = require_patient_access(patient_id)
    rows = db.session.scalars(
        select(DoseWindow).where(DoseWindow.patient_id == patient.id).order_by(DoseWindow.target_time.nulls_last())
    ).all()
    return {"dose_windows": [serializers.window(w) for w in rows]}


def _check_window(w: DoseWindow) -> None:
    if w.missed_after_min < w.on_time_after_min:
        raise bad_request("INVALID_WINDOW", "missed_after_min must be at least on_time_after_min.")
    if w.kind not in ("generic", "custom") and w.target_time is None:
        raise bad_request("INVALID_WINDOW", f"The {w.name} window needs a target_time.")
    if w.kind == "generic" and w.target_time is not None:
        raise bad_request("INVALID_WINDOW", "The generic window has no target_time; set times per schedule.")


@blp.route("/patients/<uuid:patient_id>/dose-windows", methods=["POST"])
@jwt_required()
@blp.arguments(WindowCreateSchema)
@blp.response(201)
def create_window(data, patient_id: uuid.UUID):
    patient = require_patient_access(patient_id, write=True)
    w = DoseWindow(patient_id=patient.id, kind="custom", **data)
    _check_window(w)
    db.session.add(w)
    db.session.commit()
    return serializers.window(w)


@blp.route("/dose-windows/<uuid:window_id>", methods=["PUT"])
@jwt_required()
@blp.arguments(WindowUpdateSchema)
@blp.response(200)
def update_window(data, window_id: uuid.UUID):
    """Edit a window. Schedule times that used the old target_time move with it; not-yet-due doses are rebuilt."""
    w = db.session.get(DoseWindow, window_id)
    if w is None:
        raise not_found("Dose window")
    require_patient_access(w.patient_id, write=True)
    old_target = w.target_time
    for field, value in data.items():
        setattr(w, field, value)
    _check_window(w)
    if "target_time" in data and old_target is not None and w.target_time != old_target:
        db.session.execute(
            update(DoseScheduleTime)
            .where(DoseScheduleTime.dose_window_id == w.id, DoseScheduleTime.local_time == old_target)
            .values(local_time=w.target_time)
        )
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        raise conflict("DUPLICATE_TIME", "A schedule already has a dose at that time.")
    scheduling.regenerate_future(w.patient_id)
    db.session.commit()
    return serializers.window(w)
