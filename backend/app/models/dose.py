import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import created_at_col, in_list, tstz, uuid_pk
from app.models.enums import CONFIRMATION_METHODS, DOSE_STATUSES, FINAL_DOSE_STATUSES, MATCH_STATUSES
from app.models.medication import Medication
from app.models.prescription import DoseSchedule, DoseScheduleTime, PrescriptionItem
from app.utils.time import utcnow


class DoseEvent(db.Model):
    """A concrete scheduled dose. Regular table (mutable and referenced by other tables)."""

    __tablename__ = "dose_events"
    __table_args__ = (
        UniqueConstraint("schedule_id", "scheduled_at"),
        CheckConstraint(in_list("status", DOSE_STATUSES), name="status"),
        CheckConstraint(
            f"confirmation_method IS NULL OR {in_list('confirmation_method', CONFIRMATION_METHODS)}",
            name="confirmation_method",
        ),
        CheckConstraint(
            "on_time_start <= scheduled_at AND scheduled_at <= on_time_end "
            "AND on_time_end <= missed_after AND missed_after <= confirm_deadline",
            name="window_order",
        ),
        CheckConstraint(
            "status NOT IN ('taken_on_time', 'taken_late') OR "
            "(confirmation_method IS NOT NULL AND confirmed_at IS NOT NULL "
            "AND taken_at IS NOT NULL AND quantity_taken IS NOT NULL)",
            name="taken_fields",
        ),
        CheckConstraint("quantity_taken IS NULL OR quantity_taken > 0", name="quantity_taken_positive"),
        Index("ix_dose_events_patient_scheduled", "patient_id", "scheduled_at"),
        Index("ix_dose_events_status_missed_after", "status", "missed_after"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Denormalized for query speed and so history survives prescription versioning.
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    prescription_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prescription_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    medication_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("medications.id"), nullable=False, index=True)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dose_schedules.id", ondelete="CASCADE"), nullable=False
    )
    schedule_time_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("dose_schedule_times.id", ondelete="CASCADE"), nullable=False
    )
    scheduled_at: Mapped[datetime] = tstz(nullable=False)
    on_time_start: Mapped[datetime] = tstz(nullable=False)
    on_time_end: Mapped[datetime] = tstz(nullable=False)
    missed_after: Mapped[datetime] = tstz(nullable=False)
    confirm_deadline: Mapped[datetime] = tstz(nullable=False)
    window_name: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    dose_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_after_missed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmation_method: Mapped[str | None] = mapped_column(String(10))
    confirmed_at: Mapped[datetime | None] = tstz()
    taken_at: Mapped[datetime | None] = tstz()
    quantity_taken: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    # Points at vision_observations.event_id; no FK because that table is a hypertable.
    observation_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = created_at_col()

    item: Mapped[PrescriptionItem] = relationship()
    medication: Mapped[Medication] = relationship()
    schedule: Mapped[DoseSchedule] = relationship()
    schedule_time: Mapped[DoseScheduleTime] = relationship()


class DoseOutcome(db.Model):
    """Append/upsert log of final dose statuses. TimescaleDB hypertable on scheduled_at."""

    __tablename__ = "dose_outcomes"
    __table_args__ = (
        PrimaryKeyConstraint("dose_event_id", "scheduled_at"),
        CheckConstraint(in_list("status", FINAL_DOSE_STATUSES), name="status"),
        Index("ix_dose_outcomes_patient_time", "patient_id", "scheduled_at"),
    )

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dose_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    medication_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("medications.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    dose_mismatch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delay_minutes: Mapped[int | None] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class VisionObservation(db.Model):
    """One scan from the client. TimescaleDB hypertable on observed_at."""

    __tablename__ = "vision_observations"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "observed_at"),
        CheckConstraint(
            f"match_status IS NULL OR {in_list('match_status', MATCH_STATUSES)}", name="match_status"
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        Index("ix_vision_observations_event_id", "event_id"),
        Index("ix_vision_observations_patient_time", "patient_id", "observed_at"),
    )

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    drug_name: Mapped[str] = mapped_column(String(200), nullable=False)
    strength: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    medication_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("medications.id"))
    dose_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("dose_events.id", ondelete="SET NULL"))
    match_status: Mapped[str | None] = mapped_column(String(20))
    match_score: Mapped[float | None] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    received_at: Mapped[datetime] = created_at_col()
