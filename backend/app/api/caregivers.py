"""Caregiver invites and links. Caregivers are view-only (plan.md 5.2)."""

import secrets
import uuid
from datetime import timedelta

from flask_jwt_extended import current_user, jwt_required
from flask_smorest import Blueprint
from sqlalchemy import func, select

from app import serializers
from app.errors import ApiError, bad_request, forbidden, not_found
from app.extensions import db
from app.models import CaregiverLink, User
from app.models.enums import DEFAULT_PERMISSIONS
from app.schemas import AcceptInviteSchema, InviteSchema, UpdateLinkSchema
from app.services.permissions import require_patient_access
from app.utils.time import utcnow

blp = Blueprint("caregivers", __name__, description="Caregiver linking")

INVITE_TTL = timedelta(days=7)
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I for elderly-friendly codes


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


@blp.route("/patients/<uuid:patient_id>/caregivers/invite", methods=["POST"])
@jwt_required()
@blp.arguments(InviteSchema)
@blp.response(201)
def invite(data, patient_id: uuid.UUID):
    """Patient invites an existing caregiver account by email. Returns a 6-character code to share."""
    patient = require_patient_access(patient_id, write=True)
    caregiver = db.session.scalar(select(User).where(func.lower(User.email) == data["email"].strip().lower()))
    if caregiver is None or caregiver.role != "caregiver":
        raise not_found("Caregiver account with that email (ask them to register as a caregiver first)")
    link = db.session.scalar(
        select(CaregiverLink).where(CaregiverLink.patient_id == patient.id, CaregiverLink.caregiver_id == caregiver.id)
    )
    if link is not None and link.status == "active":
        raise ApiError(409, "ALREADY_LINKED", "This caregiver is already linked.")
    if link is None:
        link = CaregiverLink(patient_id=patient.id, caregiver_id=caregiver.id, permissions=dict(DEFAULT_PERMISSIONS))
        db.session.add(link)
    link.status = "pending"
    link.invite_code = _new_code()
    link.invite_expires_at = utcnow() + INVITE_TTL
    db.session.commit()
    return serializers.caregiver_link(link, include_code=True)


@blp.route("/caregivers/accept", methods=["POST"])
@jwt_required()
@blp.arguments(AcceptInviteSchema)
@blp.response(200)
def accept(data):
    """The invited caregiver accepts with the code."""
    code = data["code"].strip().upper()
    link = db.session.scalar(select(CaregiverLink).where(CaregiverLink.invite_code == code))
    if link is None or link.status != "pending":
        raise not_found("Invite")
    if link.caregiver_id != current_user.id:
        raise forbidden("This invite was sent to a different account.")
    if link.invite_expires_at and link.invite_expires_at < utcnow():
        raise bad_request("INVITE_EXPIRED", "This invite has expired. Ask the patient to send a new one.")
    link.status = "active"
    link.invite_code = None
    link.invite_expires_at = None
    db.session.commit()
    return serializers.caregiver_link(link)


@blp.route("/patients/<uuid:patient_id>/caregivers")
@jwt_required()
@blp.response(200)
def list_caregivers(patient_id: uuid.UUID):
    patient = require_patient_access(patient_id)
    links = db.session.scalars(
        select(CaregiverLink)
        .where(CaregiverLink.patient_id == patient.id, CaregiverLink.status != "revoked")
        .order_by(CaregiverLink.created_at)
    ).all()
    is_patient = current_user.id == patient.id
    return {"caregivers": [serializers.caregiver_link(link, include_code=is_patient) for link in links]}


@blp.route("/caregiver-links/<uuid:link_id>", methods=["PATCH"])
@jwt_required()
@blp.arguments(UpdateLinkSchema)
@blp.response(200)
def update_link(data, link_id: uuid.UUID):
    """Patient toggles receive_alerts or revokes the link."""
    link = db.session.get(CaregiverLink, link_id)
    if link is None:
        raise not_found("Caregiver link")
    require_patient_access(link.patient_id, write=True)
    if "receive_alerts" in data:
        link.permissions = {**link.permissions, "receive_alerts": data["receive_alerts"]}
    if data.get("status") == "revoked":
        link.status = "revoked"
        link.invite_code = None
    db.session.commit()
    return serializers.caregiver_link(link)
