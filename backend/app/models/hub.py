"""Tables for the /hub compatibility layer (the React dashboard's contract).

They hold only what the core schema has no place for: dashboard settings and phone
contacts, per-bottle label details, integer IDs the UI uses, label-scan sessions,
wearable events, supply alerts, and "remind Rosa" requests. Doses, stock, schedules,
and prescriptions stay in the core tables.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import created_at_col, in_list, tstz
from app.utils.time import utcnow

SCAN_STATUSES = ("reading", "asking_patient", "needs_caregiver", "complete")
EVENT_TYPES = ("wrong_bottle", "double_dose")
ALERT_TYPES = ("low_7", "low_5", "low_3", "no_refills")
HUB_METHODS = ("voice", "button", "dashboard", "scan")  # scan = confirmed after a Track-tab dose scan


def _int_pk():
    # Integer IDs because the dashboard contract uses integers.
    return mapped_column(Integer, Identity(start=1), primary_key=True)


class HubSettings(db.Model):
    __tablename__ = "hub_settings"

    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class HubMedication(db.Model):
    """Label details per tracked bottle. `id` is the dashboard's medication id (stable across prescription versions)."""

    __tablename__ = "hub_medications"
    __table_args__ = (
        UniqueConstraint("patient_id", "medication_id"),
        CheckConstraint("refills_remaining IS NULL OR refills_remaining >= 0", name="refills_nonneg"),
        CheckConstraint("quantity_start IS NULL OR quantity_start > 0", name="quantity_start_positive"),
    )

    id: Mapped[int] = _int_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    medication_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("medications.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    quantity_start: Mapped[int | None] = mapped_column(Integer)
    refills_remaining: Mapped[int | None] = mapped_column(Integer)
    otc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fill_date: Mapped[date | None] = mapped_column(Date)
    prescriber: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    prescriber_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    pharmacy_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    pharmacy_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    confidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = created_at_col()


class HubDoseRef(db.Model):
    """Integer id + how the dose was logged (voice/button/dashboard) for a core dose_events row."""

    __tablename__ = "hub_dose_refs"
    __table_args__ = (CheckConstraint(f"method IS NULL OR {in_list('method', HUB_METHODS)}", name="method"),)

    id: Mapped[int] = _int_pk()
    dose_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dose_events.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    method: Mapped[str | None] = mapped_column(String(20))


class HubScan(db.Model):
    """A label-scan session (one bottle, one or more photos). Images are never stored."""

    __tablename__ = "hub_scans"
    __table_args__ = (CheckConstraint(in_list("status", SCAN_STATUSES), name="status"),)

    id: Mapped[int] = _int_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="reading")
    photos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False)          # {key: {value, state}}
    confidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {key: float}
    instructions: Mapped[str | None] = mapped_column(Text)               # raw label instructions, if read
    dosage_form: Mapped[str | None] = mapped_column(String(50))          # from inference, e.g. "capsule"; NULL = unknown
    dose_unit: Mapped[str | None] = mapped_column(String(30))            # from inference dose unit; NULL = unknown
    guidance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)    # last photo's camera guidance
    history: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    medication_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hub_medications.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class HubEvent(db.Model):
    """Something the wearable caught (wrong bottle, double dose)."""

    __tablename__ = "hub_events"
    __table_args__ = (CheckConstraint(in_list("type", EVENT_TYPES), name="type"),)

    id: Mapped[int] = _int_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = tstz(nullable=False)


class HubAlert(db.Model):
    """A supply text sent to the dashboard's contacts. Once per type per bottle until a refill clears low_* alerts."""

    __tablename__ = "hub_alerts"
    __table_args__ = (
        UniqueConstraint("hub_medication_id", "type"),
        CheckConstraint(in_list("type", ALERT_TYPES), name="type"),
    )

    id: Mapped[int] = _int_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    hub_medication_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hub_medications.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = tstz(nullable=False)


class HubReminder(db.Model):
    """'Remind Rosa' requests from the dashboard."""

    __tablename__ = "hub_reminders"

    id: Mapped[int] = _int_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    hub_medication_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hub_medications.id", ondelete="CASCADE"), nullable=False
    )
    slot: Mapped[str | None] = mapped_column(String(5))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    sent_at: Mapped[datetime] = tstz(nullable=False)
