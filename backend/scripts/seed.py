"""Demo data for the UI teams: python -m scripts.seed  (run from backend/)

Creates a patient, a linked caregiver, an active prescription (Metformin 500 mg at
breakfast + dinner, Lisinopril 10 mg at breakfast), stock, upcoming doses, and seven
days of synthetic dose history so adherence charts have data. Synthetic data only.

Password comes from SEED_PASSWORD (default shown below is for local demos only).
"""

import os
import sys
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app import create_app
from app.extensions import db
from app.models import CaregiverLink, DoseEvent, Prescription, User
from app.models.enums import DEFAULT_PERMISSIONS
from app.services import adherence, inventory, prescriptions, scheduling
from app.utils.time import get_zone, utcnow

PATIENT_EMAIL = "demo.patient@example.com"
CAREGIVER_EMAIL = "demo.caregiver@example.com"
PASSWORD = os.getenv("SEED_PASSWORD", "demo-password-123")
TZ = "America/New_York"

# Deterministic history pattern per (day offset, schedule time index): status, minutes after scheduled.
PATTERN = ["on_time", "on_time", "late", "on_time", "missed", "on_time", "on_time", "skipped", "on_time", "late"]


def _user(name, email, role):
    from argon2 import PasswordHasher

    user = User(name=name, email=email, password_hash=PasswordHasher().hash(PASSWORD), role=role, timezone=TZ)
    db.session.add(user)
    db.session.flush()
    return user


def _history(patient: User, days: int = 7) -> int:
    """Insert past dose events + outcomes for the active schedules."""
    now = utcnow()
    tz = get_zone(TZ)
    created = 0
    k = 0
    for schedule in scheduling._active_schedules(patient.id):
        today = now.astimezone(tz).date()
        occurrences = scheduling.schedule_occurrences(schedule, today - timedelta(days=days), today)
        for i, (scheduled_at, st) in enumerate(occurrences):
            w = st.window
            missed_after = scheduled_at + timedelta(minutes=w.missed_after_min)
            if missed_after >= now:
                continue  # the live generator owns current/future doses
            next_at = occurrences[i + 1][0] if i + 1 < len(occurrences) else scheduled_at + timedelta(hours=24)
            event = DoseEvent(
                id=uuid.uuid4(),
                patient_id=patient.id,
                prescription_item_id=schedule.item.id,
                medication_id=schedule.item.medication_id,
                schedule_id=schedule.id,
                schedule_time_id=st.id,
                scheduled_at=scheduled_at,
                on_time_start=scheduled_at - timedelta(minutes=w.on_time_before_min),
                on_time_end=scheduled_at + timedelta(minutes=w.on_time_after_min),
                missed_after=missed_after,
                confirm_deadline=max(missed_after, min(next_at, scheduled_at + timedelta(hours=24))),
                window_name=w.name,
                status="pending",
            )
            kind = PATTERN[k % len(PATTERN)]
            k += 1
            if kind in ("on_time", "late"):
                event.taken_at = scheduled_at + timedelta(minutes=10 if kind == "on_time" else w.on_time_after_min + 25)
                event.confirmed_at = event.taken_at
                event.confirmation_method = "manual"
                event.quantity_taken = schedule.item.dose_quantity
                event.status = adherence.classify(event, event.taken_at)
            else:
                event.status = "missed" if kind == "missed" else "skipped"
            db.session.add(event)
            db.session.flush()
            adherence.upsert_outcome(event)
            created += 1
    return created


def main() -> int:
    app = create_app()
    with app.app_context():
        if db.session.scalar(select(User).where(func.lower(User.email) == PATIENT_EMAIL)):
            print(f"Seed data already present ({PATIENT_EMAIL}). Nothing to do.")
            return 0
        patient = _user("Ada Demo", PATIENT_EMAIL, "patient")
        prescriptions.seed_default_windows(patient.id)
        caregiver = _user("Cara Demo", CAREGIVER_EMAIL, "caregiver")
        db.session.add(
            CaregiverLink(patient_id=patient.id, caregiver_id=caregiver.id, status="active", permissions=dict(DEFAULT_PERMISSIONS))
        )
        db.session.flush()

        rx, _ = prescriptions.create_draft(
            patient,
            {
                "items": [
                    {"name": "Metformin", "strength": "500 mg", "dosage_form": "tablet", "dose_quantity": 1,
                     "dose_unit": "tablet", "route": "oral", "quantity_prescribed": 60, "refills_authorized": 2,
                     "instructions": "Take 1 tablet by mouth twice daily with meals."},
                    {"name": "Lisinopril", "strength": "10 mg", "dosage_form": "tablet", "dose_quantity": 1,
                     "dose_unit": "tablet", "route": "oral", "quantity_prescribed": 30, "refills_authorized": 5,
                     "instructions": "Take 1 tablet by mouth once daily."},
                ]
            },
        )
        metformin, lisinopril = rx.items
        start = (utcnow() - timedelta(days=8)).astimezone(get_zone(TZ)).date()
        prescriptions.set_schedule(metformin, {"start_date": start, "times": [{"window_kind": "breakfast"}, {"window_kind": "dinner"}]})
        prescriptions.set_schedule(lisinopril, {"start_date": start, "times": [{"window_kind": "breakfast"}]})
        result = prescriptions.activate(db.session.get(Prescription, rx.id), user_id=patient.id)
        history = _history(patient)
        # Stock after a week of doses (keep it simple: subtract 14 and 7).
        for med, used in ((metformin.medication_id, 14), (lisinopril.medication_id, 7)):
            inv = inventory.get_inventory(patient.id, med)
            inventory.set_quantity(inv, inv.quantity_remaining - used, created_by=patient.id, note="seed: past week")
        db.session.commit()
        print("Seeded demo data:")
        print(f"  patient   {PATIENT_EMAIL}  (id {patient.id})")
        print(f"  caregiver {CAREGIVER_EMAIL}  (id {caregiver.id})")
        print("  password  from SEED_PASSWORD (or the local default in scripts/seed.py)")
        print(f"  upcoming dose events: {result['dose_events_created']}, history events: {history}")
        if result["warnings"]:
            print(f"  OpenFDA warnings: {[w['code'] for w in result['warnings']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
