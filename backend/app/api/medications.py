import uuid

from flask_jwt_extended import jwt_required
from flask_smorest import Blueprint
from sqlalchemy import select

from app import serializers
from app.errors import not_found
from app.extensions import db
from app.models import Medication
from app.schemas import SearchQuerySchema
from app.services import openfda

blp = Blueprint("medications", __name__, description="Medication lookup and OpenFDA verification")


@blp.route("/medications/search")
@jwt_required()
@blp.arguments(SearchQuerySchema, location="query")
@blp.response(200)
def search(args):
    """Known medications plus OpenFDA candidates for a name."""
    q = args["q"].strip()
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    known = db.session.scalars(
        select(Medication).where(Medication.name.ilike(pattern, escape="\\")).order_by(Medication.name).limit(20)
    ).all()
    fda = openfda.search(q)
    return {
        "known": [serializers.medication(m) for m in known],
        "openfda": {"available": fda["available"], "candidates": fda["candidates"]},
    }


@blp.route("/medications/<uuid:medication_id>/verify", methods=["POST"])
@jwt_required()
@blp.response(200)
def verify(medication_id: uuid.UUID):
    """Re-run OpenFDA verification for one medication."""
    med = db.session.get(Medication, medication_id)
    if med is None:
        raise not_found("Medication")
    result = openfda.verify_medication(med)
    db.session.commit()
    return {"medication": serializers.medication(med), "verification": result}
