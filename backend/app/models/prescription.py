import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import created_at_col, in_list, tstz, uuid_pk
from app.models.enums import FREQUENCIES, PRESCRIPTION_STATUSES, WINDOW_KINDS
from app.models.medication import Medication
from app.utils.time import utcnow


class Prescription(db.Model):
    __tablename__ = "prescriptions"
    __table_args__ = (
        UniqueConstraint("patient_id", "version"),
        CheckConstraint(in_list("status", PRESCRIPTION_STATUSES), name="status"),
        CheckConstraint("version >= 1", name="version_positive"),
        # db.md: at most one active prescription per patient.
        Index(
            "uq_prescriptions_one_active",
            "patient_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    effective_at: Mapped[datetime | None] = tstz()
    source_document_uri: Mapped[str | None] = mapped_column(String(2048))
    created_at: Mapped[datetime] = created_at_col()

    items: Mapped[list["PrescriptionItem"]] = relationship(
        back_populates="prescription", cascade="all, delete-orphan", order_by="PrescriptionItem.created_at"
    )


class PrescriptionItem(db.Model):
    """Fields marked required in db.md are enforced at activation; drafts are incomplete by design."""

    __tablename__ = "prescription_items"
    __table_args__ = (
        CheckConstraint("dose_quantity IS NULL OR dose_quantity > 0", name="dose_quantity_positive"),
        CheckConstraint("quantity_prescribed IS NULL OR quantity_prescribed >= 0", name="quantity_prescribed_nonneg"),
        CheckConstraint("refills_authorized IS NULL OR refills_authorized >= 0", name="refills_nonneg"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    prescription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prescriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    medication_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("medications.id"), nullable=False, index=True)
    dose_quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    dose_unit: Mapped[str | None] = mapped_column(String(30))
    route: Mapped[str | None] = mapped_column(String(50))
    quantity_prescribed: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    refills_authorized: Mapped[int | None] = mapped_column(Integer)
    instructions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()

    prescription: Mapped[Prescription] = relationship(back_populates="items")
    medication: Mapped[Medication] = relationship()
    schedule: Mapped["DoseSchedule | None"] = relationship(
        back_populates="item", cascade="all, delete-orphan", uselist=False
    )


class DoseWindow(db.Model):
    __tablename__ = "dose_windows"
    __table_args__ = (
        CheckConstraint(in_list("kind", WINDOW_KINDS), name="kind"),
        CheckConstraint(
            "on_time_before_min >= 0 AND on_time_after_min >= 0 AND missed_after_min >= 0",
            name="minutes_nonneg",
        ),
        CheckConstraint("missed_after_min >= on_time_after_min", name="missed_after_on_time"),
        CheckConstraint(
            "kind IN ('generic', 'custom') OR target_time IS NOT NULL", name="preset_target_time"
        ),
        # db.md: one row per patient for each preset kind.
        Index(
            "uq_dose_windows_preset",
            "patient_id",
            "kind",
            unique=True,
            postgresql_where=text("kind <> 'custom'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    target_time: Mapped[time | None] = mapped_column(Time)
    on_time_before_min: Mapped[int] = mapped_column(Integer, nullable=False)
    on_time_after_min: Mapped[int] = mapped_column(Integer, nullable=False)
    missed_after_min: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class DoseSchedule(db.Model):
    __tablename__ = "dose_schedules"
    __table_args__ = (
        CheckConstraint(in_list("frequency", FREQUENCIES), name="frequency"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="date_range"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # One schedule per prescription item; PUT replaces it.
    prescription_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prescription_items.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="daily")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = created_at_col()

    item: Mapped[PrescriptionItem] = relationship(back_populates="schedule")
    times: Mapped[list["DoseScheduleTime"]] = relationship(
        back_populates="schedule", cascade="all, delete-orphan", order_by="DoseScheduleTime.local_time"
    )


class DoseScheduleTime(db.Model):
    __tablename__ = "dose_schedule_times"
    __table_args__ = (UniqueConstraint("schedule_id", "local_time"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dose_schedules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    local_time: Mapped[time] = mapped_column(Time, nullable=False)
    dose_window_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("dose_windows.id"), nullable=False, index=True)

    schedule: Mapped[DoseSchedule] = relationship(back_populates="times")
    window: Mapped[DoseWindow] = relationship()
