import uuid
from datetime import datetime

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.utils.time import utcnow

# Shared column helpers.


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


def tstz(nullable: bool = True):
    return mapped_column(DateTime(timezone=True), nullable=nullable)


def in_list(column: str, values: list[str] | tuple[str, ...]) -> str:
    """SQL text for a CHECK (column IN (...)) constraint."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"
