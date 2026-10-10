from flask_smorest import Blueprint
from sqlalchemy import text

from app.extensions import db
from app.utils.time import utcnow

blp = Blueprint("health", __name__, description="Service health")


@blp.route("/health")
@blp.response(200)
@blp.doc(security=[])
def health():
    """Liveness + database check (no auth)."""
    try:
        version = db.session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
        ).scalar()
        database = "ok"
    except Exception:  # noqa: BLE001 - report, don't crash the health check
        db.session.rollback()
        version, database = None, "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "service": "medcheck-backend",
        "database": database,
        "timescaledb": version,
        "time": utcnow(),
    }
