"""Registration, login, token refresh, current user, push tokens."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    current_user,
    jwt_required,
)
from flask_smorest import Blueprint
from sqlalchemy import func, select

from app import serializers
from app.errors import ApiError, conflict, not_found
from app.extensions import db
from app.models import CaregiverLink, DoseSchedule, Prescription, PrescriptionItem, PushToken, User
from app.schemas import LoginSchema, PushTokenSchema, RegisterSchema, UpdateMeSchema
from app.services import scheduling
from app.services.prescriptions import seed_default_windows

blp = Blueprint("auth", __name__, description="Auth and current user")
hasher = PasswordHasher()
_DUMMY_HASH = hasher.hash("timing-equalizer-not-a-password")


def _tokens(user: User) -> dict:
    claims = {"role": user.role}
    return {
        "access_token": create_access_token(identity=str(user.id), additional_claims=claims),
        "refresh_token": create_refresh_token(identity=str(user.id), additional_claims=claims),
        "token_type": "Bearer",
    }


@blp.route("/auth/register", methods=["POST"])
@blp.arguments(RegisterSchema)
@blp.response(201)
@blp.doc(security=[])
def register(data):
    """Create a patient or caregiver account. Patients get the five default dose windows."""
    email = data["email"].strip().lower()
    if db.session.scalar(select(User).where(func.lower(User.email) == email)):
        raise conflict("EMAIL_TAKEN", "An account with that email already exists.")
    user = User(
        name=data["name"].strip(),
        email=email,
        password_hash=hasher.hash(data["password"]),
        role=data["role"],
        timezone=data["timezone"],
        phone=data.get("phone"),
    )
    db.session.add(user)
    db.session.flush()
    if user.role == "patient":
        seed_default_windows(user.id)
    db.session.commit()
    return {"user": serializers.user(user), **_tokens(user)}


@blp.route("/auth/login", methods=["POST"])
@blp.arguments(LoginSchema)
@blp.response(200)
@blp.doc(security=[])
def login(data):
    user = db.session.scalar(select(User).where(func.lower(User.email) == data["email"].strip().lower()))
    try:
        hasher.verify(user.password_hash if user else _DUMMY_HASH, data["password"])
        if user is None:
            raise VerificationError()
    except (VerificationError, InvalidHashError):
        raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect.")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data["password"])
        db.session.commit()
    return {"user": serializers.user(user), **_tokens(user)}


@blp.route("/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
@blp.response(200)
def refresh():
    """Send the refresh token as the Bearer token; returns a new access token."""
    user = current_user
    return {
        "access_token": create_access_token(identity=str(user.id), additional_claims={"role": user.role}),
        "token_type": "Bearer",
    }


def _me_payload(user: User) -> dict:
    data = {"user": serializers.user(user)}
    if user.role == "patient":
        links = db.session.scalars(
            select(CaregiverLink).where(CaregiverLink.patient_id == user.id, CaregiverLink.status != "revoked")
        ).all()
        data["caregivers"] = [serializers.caregiver_link(link) for link in links]
    else:
        links = db.session.scalars(
            select(CaregiverLink).where(CaregiverLink.caregiver_id == user.id, CaregiverLink.status == "active")
        ).all()
        data["patients"] = [serializers.caregiver_link(link) for link in links]
    return data


@blp.route("/me")
@jwt_required()
@blp.response(200)
def get_me():
    return _me_payload(current_user)


@blp.route("/me", methods=["PATCH"])
@jwt_required()
@blp.arguments(UpdateMeSchema)
@blp.response(200)
def update_me(data):
    """Update name, phone (E.164), timezone, and notification preferences."""
    user = current_user
    tz_changed = "timezone" in data and data["timezone"] != user.timezone
    for field, value in data.items():
        setattr(user, field, value)
    if tz_changed and user.role == "patient":
        schedules = db.session.scalars(
            select(DoseSchedule)
            .join(PrescriptionItem, DoseSchedule.prescription_item_id == PrescriptionItem.id)
            .join(Prescription)
            .where(Prescription.patient_id == user.id, Prescription.status.in_(("draft", "active")))
        ).all()
        for s in schedules:
            s.timezone = user.timezone
        db.session.flush()
        scheduling.regenerate_future(user.id)
    db.session.commit()
    return _me_payload(user)


@blp.route("/me/push-tokens", methods=["POST"])
@jwt_required()
@blp.arguments(PushTokenSchema)
@blp.response(201)
def add_push_token(data):
    """Register an FCM web push token for this browser. iOS push is not supported."""
    token = db.session.scalar(select(PushToken).where(PushToken.token == data["token"]))
    if token is None:
        token = PushToken(user_id=current_user.id, token=data["token"], platform=data["platform"])
        db.session.add(token)
    else:
        token.user_id = current_user.id  # browser now belongs to whoever logged in last
    db.session.commit()
    return {"id": token.id, "platform": token.platform, "created_at": token.created_at}


@blp.route("/me/push-tokens/<path:token>", methods=["DELETE"])
@jwt_required()
@blp.response(204)
def delete_push_token(token):
    row = db.session.scalar(select(PushToken).where(PushToken.token == token, PushToken.user_id == current_user.id))
    if row is None:
        raise not_found("Push token")
    db.session.delete(row)
    db.session.commit()
    return None
