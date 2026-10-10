"""The only code path that changes medication_inventory.quantity_remaining (plan.md 5.9).

Every change writes a matching inventory_transactions row in the same DB transaction.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.errors import ApiError
from app.extensions import db
from app.models import InventoryTransaction, MedicationInventory
from app.utils.time import utcnow


class InsufficientStock(ApiError):
    def __init__(self, remaining: Decimal, delta: Decimal):
        super().__init__(
            409,
            "INSUFFICIENT_STOCK",
            "This change would make the recorded quantity negative. Correct the stock first.",
            {"quantity_remaining": float(remaining), "delta": float(delta)},
        )


def get_inventory(patient_id: uuid.UUID, medication_id: uuid.UUID, lock: bool = False) -> MedicationInventory | None:
    stmt = select(MedicationInventory).where(
        MedicationInventory.patient_id == patient_id, MedicationInventory.medication_id == medication_id
    )
    if lock:
        stmt = stmt.with_for_update()
    return db.session.scalar(stmt)


def ensure_inventory(patient_id: uuid.UUID, medication_id: uuid.UUID, unit: str) -> MedicationInventory:
    inv = get_inventory(patient_id, medication_id)
    if inv is None:
        inv = MedicationInventory(
            patient_id=patient_id, medication_id=medication_id, quantity_unit=unit, quantity_remaining=None
        )
        db.session.add(inv)
        db.session.flush()
    return inv


def apply_transaction(
    patient_id: uuid.UUID,
    medication_id: uuid.UUID,
    delta: Decimal,
    reason: str,
    *,
    dose_event_id: uuid.UUID | None = None,
    refill_request_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    note: str | None = None,
    initialize_if_unknown: bool = False,
) -> InventoryTransaction | None:
    """Apply a signed delta. Returns None if stock is untracked (unknown) and not initialized here.

    Raises InsufficientStock if the result would be negative.
    """
    delta = Decimal(delta)
    inv = get_inventory(patient_id, medication_id, lock=True)
    if inv is None:
        return None
    if inv.quantity_remaining is None:
        if not (initialize_if_unknown and delta > 0):
            return None
        new_quantity = delta
    else:
        new_quantity = inv.quantity_remaining + delta
        if new_quantity < 0:
            raise InsufficientStock(inv.quantity_remaining, delta)
    txn = InventoryTransaction(
        patient_id=patient_id,
        medication_id=medication_id,
        delta=delta,
        reason=reason,
        dose_event_id=dose_event_id,
        refill_request_id=refill_request_id,
        created_by=created_by,
        note=note,
    )
    db.session.add(txn)
    inv.quantity_remaining = new_quantity
    inv.updated_at = utcnow()
    db.session.flush()
    return txn


def set_quantity(
    inv: MedicationInventory, quantity: Decimal, *, created_by: uuid.UUID, note: str | None = None
) -> InventoryTransaction | None:
    """Manual initialize/correct. Writes a manual_adjustment for the difference."""
    quantity = Decimal(quantity)
    db.session.refresh(inv, with_for_update=True)
    old = inv.quantity_remaining
    inv.last_reconciled_at = utcnow()
    inv.updated_at = utcnow()
    delta = quantity - (old if old is not None else Decimal(0))
    if delta == 0:
        # Nothing moved (or unknown -> 0). No transaction since delta must be non-zero.
        inv.quantity_remaining = quantity
        db.session.flush()
        return None
    txn = InventoryTransaction(
        patient_id=inv.patient_id,
        medication_id=inv.medication_id,
        delta=delta,
        reason="manual_adjustment",
        created_by=created_by,
        note=note or ("initialized" if old is None else "manual correction"),
    )
    db.session.add(txn)
    inv.quantity_remaining = quantity
    db.session.flush()
    return txn
