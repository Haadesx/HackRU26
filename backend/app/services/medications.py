import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.extensions import db
from app.models import Medication
from app.services.normalize import display_name, normalize_strength
from app.utils.time import utcnow


def find_or_create(name: str, strength=None, dosage_form: str | None = None) -> Medication:
    """Dedupe on (lower(name), strength, dosage_form), matching the unique index."""
    name = display_name(name)
    strength = normalize_strength(strength)
    dosage_form = dosage_form.strip().lower() if dosage_form and dosage_form.strip() else None

    def _lookup():
        return db.session.scalar(
            select(Medication).where(
                func.lower(Medication.name) == name.lower(),
                func.coalesce(Medication.strength, "") == (strength or ""),
                func.coalesce(Medication.dosage_form, "") == (dosage_form or ""),
            )
        )

    med = _lookup()
    if med is not None:
        return med
    db.session.execute(
        insert(Medication)
        .values(
            id=uuid.uuid4(),
            name=name,
            strength=strength,
            dosage_form=dosage_form,
            verified=False,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing()
    )
    return _lookup()
