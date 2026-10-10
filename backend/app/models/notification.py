import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import created_at_col, in_list, tstz, uuid_pk
from app.models.enums import CHANNELS, DELIVERY_STATUSES, REMINDER_KINDS, REMINDER_STATUSES


class Reminder(db.Model):
    """A logical notification to one recipient. Channels fan out to notification_deliveries."""

    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(in_list("kind", REMINDER_KINDS), name="kind"),
        CheckConstraint(in_list("status", REMINDER_STATUSES), name="status"),
        # db.md: dose_event_id + kind + recipient unique when dose_event_id is set.
        Index(
            "uq_reminders_dose_kind_recipient",
            "dose_event_id",
            "kind",
            "recipient_user_id",
            unique=True,
            postgresql_where=text("dose_event_id IS NOT NULL"),
        ),
        Index("ix_reminders_due", "status", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[datetime] = tstz(nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    dose_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("dose_events.id", ondelete="CASCADE"))
    refill_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("refill_requests.id", ondelete="CASCADE")
    )
    sent_at: Mapped[datetime | None] = tstz()
    created_at: Mapped[datetime] = created_at_col()

    deliveries: Mapped[list["NotificationDelivery"]] = relationship(
        back_populates="reminder", cascade="all, delete-orphan"
    )


class NotificationDelivery(db.Model):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint(in_list("channel", CHANNELS), name="channel"),
        CheckConstraint(in_list("status", DELIVERY_STATUSES), name="status"),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    reminder_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reminders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    push_token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("push_tokens.id", ondelete="SET NULL")
    )
    sent_at: Mapped[datetime | None] = tstz()
    read_at: Mapped[datetime | None] = tstz()
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_col()

    reminder: Mapped[Reminder] = relationship(back_populates="deliveries")
