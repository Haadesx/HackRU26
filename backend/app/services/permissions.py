"""Single authorization helper for every patient-scoped route.

- Patients have full read/write access to themselves.
- Caregivers with an active link and the `view` permission get read access.
- Any write by anyone other than the patient is rejected. Caregivers are view-only.
"""

import uuid

from flask_jwt_extended import current_user
from sqlalchemy import select

from app.errors import forbidden, not_found
from app.extensions import db
from app.models import CaregiverLink, User


def me() -> User:
    return current_user


def active_link(patient_id: uuid.UUID, caregiver_id: uuid.UUID) -> CaregiverLink | None:
    return db.session.scalar(
        select(CaregiverLink).where(
            CaregiverLink.patient_id == patient_id,
            CaregiverLink.caregiver_id == caregiver_id,
            CaregiverLink.status == "active",
        )
    )


def require_patient_access(patient_id: uuid.UUID, write: bool = False) -> User:
    user = me()
    patient = db.session.get(User, patient_id)
    if patient is None or patient.role != "patient":
        raise not_found("Patient")
    if user.id == patient.id:
        return patient
    link = active_link(patient.id, user.id)
    if write:
        if link is not None:
            raise forbidden("Caregivers have view-only access.")
        raise forbidden()
    if link is None or not link.permissions.get("view", False):
        raise forbidden()
    return patient


def require_patient_self() -> User:
    """For routes without a patient id in the path (e.g. POST /scans): caller must be a patient."""
    user = me()
    if user.role != "patient":
        raise forbidden("Only patients can perform this action.")
    return user
