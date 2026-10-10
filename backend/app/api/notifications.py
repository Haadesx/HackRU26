"""In-app notification inbox (delivery rows with channel = in_app). The iOS app polls this."""

import uuid

from flask_jwt_extended import current_user, jwt_required
from flask_smorest import Blueprint
from sqlalchemy import func, select

from app import serializers
from app.errors import not_found
from app.extensions import db
from app.models import NotificationDelivery, Reminder
from app.schemas import NotificationsQuerySchema
from app.utils.time import utcnow

blp = Blueprint("notifications", __name__, description="In-app notifications")


def _inbox(user_id: uuid.UUID):
    return (
        select(NotificationDelivery)
        .join(Reminder)
        .where(
            Reminder.recipient_user_id == user_id,
            NotificationDelivery.channel == "in_app",
            NotificationDelivery.status == "sent",
        )
    )


@blp.route("/notifications")
@jwt_required()
@blp.arguments(NotificationsQuerySchema, location="query")
@blp.response(200)
def list_notifications(args):
    stmt = _inbox(current_user.id)
    if args["unread_only"]:
        stmt = stmt.where(NotificationDelivery.read_at.is_(None))
    rows = db.session.scalars(stmt.order_by(NotificationDelivery.sent_at.desc()).limit(args["limit"])).all()
    unread = db.session.scalar(
        select(func.count()).select_from(_inbox(current_user.id).where(NotificationDelivery.read_at.is_(None)).subquery())
    )
    return {"unread_count": unread, "notifications": [serializers.notification(d) for d in rows]}


@blp.route("/notifications/<uuid:notification_id>/read", methods=["POST"])
@jwt_required()
@blp.response(200)
def mark_read(notification_id: uuid.UUID):
    delivery = db.session.scalar(_inbox(current_user.id).where(NotificationDelivery.id == notification_id))
    if delivery is None:
        raise not_found("Notification")
    if delivery.read_at is None:
        delivery.read_at = utcnow()
        db.session.commit()
    return serializers.notification(delivery)
