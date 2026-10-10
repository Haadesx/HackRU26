import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models.base import created_at_col, tstz, uuid_pk


class Medication(db.Model):
    __tablename__ = "medications"
    __table_args__ = (
        # db.md: lower(name) + strength + dosage_form unique. COALESCE so NULLs compare equal.
        Index(
            "uq_medications_identity",
            func.lower(text("name")),
            func.coalesce(text("strength"), text("''")),
            func.coalesce(text("dosage_form"), text("''")),
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Normalized "<number> <unit>", e.g. "500 mg". Required when the prescription specifies it.
    strength: Mapped[str | None] = mapped_column(String(50))
    dosage_form: Mapped[str | None] = mapped_column(String(50))
    openfda_id: Mapped[str | None] = mapped_column(String(64))
    rxcui: Mapped[str | None] = mapped_column(String(32))
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = tstz()
    created_at: Mapped[datetime] = created_at_col()
