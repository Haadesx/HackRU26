import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import created_at_col, in_list, tstz, uuid_pk
from app.models.enums import INVENTORY_REASONS, REFILL_STATUSES
from app.models.medication import Medication
from app.models.prescription import PrescriptionItem
from app.utils.time import utcnow


class MedicationInventory(db.Model):
    __tablename__ = "medication_inventory"
    __table_args__ = (
        UniqueConstraint("patient_id", "medication_id"),
        CheckConstraint("quantity_remaining IS NULL OR quantity_remaining >= 0", name="quantity_nonneg"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    medication_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("medications.id"), nullable=False)
    # NULL = unknown (not initialized). Unknown is not zero.
    quantity_remaining: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    quantity_unit: Mapped[str] = mapped_column(String(30), nullable=False)
    last_reconciled_at: Mapped[datetime | None] = tstz()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    medication: Mapped[Medication] = relationship()


class RefillRequest(db.Model):
    __tablename__ = "refill_requests"
    __table_args__ = (
        CheckConstraint(in_list("status", REFILL_STATUSES), name="status"),
        CheckConstraint("quantity_added IS NULL OR quantity_added > 0", name="quantity_added_positive"),
        CheckConstraint(
            "status <> 'fulfilled' OR (fulfilled_at IS NOT NULL AND quantity_added IS NOT NULL)",
            name="fulfilled_fields",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    prescription_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prescription_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    appointment_at: Mapped[datetime | None] = tstz()
    pharmacy_or_provider: Mapped[str | None] = mapped_column(String(300))
    fulfilled_at: Mapped[datetime | None] = tstz()
    quantity_added: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    caregiver_notified_at: Mapped[datetime | None] = tstz()
    created_at: Mapped[datetime] = created_at_col()

    item: Mapped[PrescriptionItem] = relationship()


class InventoryTransaction(db.Model):
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint(in_list("reason", INVENTORY_REASONS), name="reason"),
        CheckConstraint(
            "(reason = 'dose' AND delta < 0) OR (reason = 'refill' AND delta > 0) "
            "OR (reason = 'manual_adjustment' AND delta <> 0)",
            name="delta_sign",
        ),
        CheckConstraint("reason <> 'dose' OR dose_event_id IS NOT NULL", name="dose_ref"),
        CheckConstraint("reason <> 'refill' OR refill_request_id IS NOT NULL", name="refill_ref"),
        # db.md: patient_id + medication_id must reference an existing medication_inventory row.
        ForeignKeyConstraint(
            ["patient_id", "medication_id"],
            ["medication_inventory.patient_id", "medication_inventory.medication_id"],
            name="fk_inventory_transactions_inventory",
            ondelete="CASCADE",
        ),
        Index("ix_inventory_transactions_patient_med", "patient_id", "medication_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    medication_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    dose_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("dose_events.id", ondelete="SET NULL"))
    refill_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("refill_requests.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()
