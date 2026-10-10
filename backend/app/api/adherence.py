"""Adherence rates from the dose_outcomes hypertable.

Buckets use TimescaleDB time_bucket in the patient's own timezone, so a 21:30 bedtime
dose counts toward the right local day. (The daily_adherence continuous aggregate is
bucketed in UTC and is kept for analytics; see docs/backend-urvi.md.)
"""

import uuid
from datetime import timedelta

from flask_jwt_extended import jwt_required
from flask_smorest import Blueprint
from sqlalchemy import text

from app.errors import bad_request
from app.extensions import db
from app.schemas import AdherenceQuerySchema
from app.services.permissions import require_patient_access
from app.utils.time import ensure_utc, utcnow

blp = Blueprint("adherence", __name__, description="Adherence analytics")

_SQL = """
SELECT time_bucket(CAST(:width AS interval), scheduled_at, :tz) AS bucket,
       count(*) FILTER (WHERE status = 'taken_on_time') AS taken_on_time,
       count(*) FILTER (WHERE status = 'taken_late')    AS taken_late,
       count(*) FILTER (WHERE status = 'missed')        AS missed,
       count(*) FILTER (WHERE status = 'skipped')       AS skipped,
       count(*) FILTER (WHERE dose_mismatch)            AS dose_mismatch,
       count(*)                                         AS total
FROM dose_outcomes
WHERE patient_id = :patient_id
  AND scheduled_at >= :start AND scheduled_at < :end
  {medication_filter}
GROUP BY bucket
ORDER BY bucket
"""

_KEYS = ("taken_on_time", "taken_late", "missed", "skipped", "dose_mismatch", "total")


def _rates(row: dict) -> dict:
    counted = row["taken_on_time"] + row["taken_late"] + row["missed"]  # skipped doses are excluded
    taken = row["taken_on_time"] + row["taken_late"]
    return {
        **row,
        "on_time_rate": round(row["taken_on_time"] / counted, 3) if counted else None,
        "taken_rate": round(taken / counted, 3) if counted else None,
    }


@blp.route("/patients/<uuid:patient_id>/adherence")
@jwt_required()
@blp.arguments(AdherenceQuerySchema, location="query")
@blp.response(200)
def adherence(args, patient_id: uuid.UUID):
    """On-time / late / missed counts and rates per local day or week. Defaults to the last 7 days."""
    patient = require_patient_access(patient_id)
    end = ensure_utc(args["end"]) if args.get("end") else utcnow()
    default_span = timedelta(days=7) if args["granularity"] == "day" else timedelta(weeks=8)
    start = ensure_utc(args["start"]) if args.get("start") else end - default_span
    if end <= start or end - start > timedelta(days=366):
        raise bad_request("INVALID_RANGE", "'to' must be after 'from' and within one year.")
    params = {
        "width": "1 day" if args["granularity"] == "day" else "1 week",
        "tz": patient.timezone,
        "patient_id": patient.id,
        "start": start,
        "end": end,
    }
    medication_filter = ""
    if args.get("medication_id"):
        medication_filter = "AND medication_id = :medication_id"
        params["medication_id"] = args["medication_id"]
    rows = db.session.execute(text(_SQL.format(medication_filter=medication_filter)), params).mappings().all()
    buckets = [_rates({"bucket_start": r["bucket"], **{k: r[k] for k in _KEYS}}) for r in rows]
    totals = {k: sum(b[k] for b in buckets) for k in _KEYS}
    return {
        "from": start,
        "to": end,
        "granularity": args["granularity"],
        "timezone": patient.timezone,
        "summary": _rates(totals),
        "buckets": buckets,
    }
