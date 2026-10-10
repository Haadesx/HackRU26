import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, UniqueConstraint, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import created_at_col, in_list, tstz, uuid_pk
from app.models.enums import DEFAULT_PERMISSIONS, LINK_STATUSES, PUSH_PLATFORMS, ROLES


class User(db.Model):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(in_list("role", ROLES), name="role"),
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/New_York")
    phone: Mapped[str | None] = mapped_column(String(20))
    sms_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_col()


class CaregiverLink(db.Model):
    __tablename__ = "caregiver_links"
    __table_args__ = (
        UniqueConstraint("patient_id", "caregiver_id"),
        CheckConstraint(in_list("status", LINK_STATUSES), name="status"),
        CheckConstraint("patient_id <> caregiver_id", name="not_self"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    caregiver_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    permissions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=lambda: dict(DEFAULT_PERMISSIONS))
    invite_code: Mapped[str | None] = mapped_column(String(16), unique=True)
    invite_expires_at: Mapped[datetime | None] = tstz()
    created_at: Mapped[datetime] = created_at_col()

    patient: Mapped[User] = relationship(foreign_keys=[patient_id])
    caregiver: Mapped[User] = relationship(foreign_keys=[caregiver_id])


class PushToken(db.Model):
    __tablename__ = "push_tokens"
    __table_args__ = (CheckConstraint(in_list("platform", PUSH_PLATFORMS), name="platform"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(4096), nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    last_used_at: Mapped[datetime | None] = tstz()
