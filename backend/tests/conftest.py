"""Tests run against a real TimescaleDB (docker compose up -d), database medcheck_test.

Migrations are applied once per session; every test starts from empty tables.
The clock is frozen through app.utils.time.freeze().
"""

import os
import uuid
from datetime import datetime, timezone

import pytest

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://medcheck:medcheck@localhost:5433/medcheck_test"
)
os.environ["JWT_SECRET_KEY"] = "test-only-secret-not-for-production-use-0123456789"
os.environ["OPENFDA_ENABLED"] = "false"
for var in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "FIREBASE_CREDENTIALS_JSON"):
    os.environ[var] = ""

from flask_migrate import upgrade  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.utils import time as clock  # noqa: E402

# Monday 2026-10-12 07:00 America/New_York (EDT, UTC-4).
T0 = datetime(2026, 10, 12, 11, 0, tzinfo=timezone.utc)

TABLES = [
    "notification_deliveries", "reminders", "inventory_transactions", "refill_requests",
    "medication_inventory", "dose_outcomes", "vision_observations", "dose_events",
    "dose_schedule_times", "dose_schedules", "dose_windows", "prescription_items",
    "prescriptions", "medications", "push_tokens", "caregiver_links", "users",
]


@pytest.fixture(scope="session")
def app():
    app = create_app({"TESTING": True})
    with app.app_context():
        upgrade()
    return app


@pytest.fixture(autouse=True)
def clean_db(app):
    with app.app_context():
        db.session.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
        db.session.commit()
    clock.freeze(T0)
    yield
    clock.freeze(None)
    with app.app_context():
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def ctx(app):
    with app.app_context():
        yield


def set_now(dt: datetime) -> None:
    clock.freeze(dt)


class Api:
    """Small helper around the Flask test client."""

    def __init__(self, client):
        self.c = client

    def register(self, role="patient", name=None, email=None, **extra):
        email = email or f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        body = {"name": name or f"Test {role.title()}", "email": email, "password": "correct-horse-battery", "role": role, **extra}
        r = self.c.post("/api/v1/auth/register", json=body)
        assert r.status_code == 201, r.get_json()
        data = r.get_json()
        return {"id": data["user"]["id"], "token": data["access_token"], "refresh": data["refresh_token"], "email": email}

    def h(self, user):
        return {"Authorization": f"Bearer {user['token']}"}

    def get(self, user, path, **kw):
        return self.c.get(f"/api/v1{path}", headers=self.h(user), **kw)

    def post(self, user, path, json=None):
        return self.c.post(f"/api/v1{path}", headers=self.h(user), json=json if json is not None else {})

    def put(self, user, path, json):
        return self.c.put(f"/api/v1{path}", headers=self.h(user), json=json)

    def patch(self, user, path, json):
        return self.c.patch(f"/api/v1{path}", headers=self.h(user), json=json)

    def link_caregiver(self, patient, caregiver):
        r = self.post(patient, f"/patients/{patient['id']}/caregivers/invite", {"email": caregiver["email"]})
        assert r.status_code == 201, r.get_json()
        r = self.post(caregiver, "/caregivers/accept", {"code": r.get_json()["invite_code"]})
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    def active_metformin(self, patient, times=("breakfast", "dinner"), quantity_prescribed=60, dose_quantity=1):
        """Draft -> schedule -> activate Metformin 500 mg, 1 tablet at the given windows."""
        r = self.post(
            patient,
            f"/patients/{patient['id']}/prescriptions",
            {
                "items": [
                    {
                        "name": "Metformin",
                        "strength": {"value": 500, "unit": "mg"},
                        "dosage_form": "tablet",
                        "dose_quantity": dose_quantity,
                        "dose_unit": "tablet",
                        "route": "oral",
                        "quantity_prescribed": quantity_prescribed,
                        "refills_authorized": 2,
                        "instructions": "Take 1 tablet by mouth with meals.",
                    }
                ]
            },
        )
        assert r.status_code == 201, r.get_json()
        rx = r.get_json()
        item_id = rx["items"][0]["id"]
        r = self.put(patient, f"/prescription-items/{item_id}/schedule", {"times": [{"window_kind": k} for k in times]})
        assert r.status_code == 200, r.get_json()
        r = self.post(patient, f"/prescriptions/{rx['id']}/activate")
        assert r.status_code == 200, r.get_json()
        return r.get_json()

    def doses(self, user, patient_id, **params):
        r = self.get(user, f"/patients/{patient_id}/doses", query_string=params)
        assert r.status_code == 200, r.get_json()
        return r.get_json()["doses"]

    def scan(self, patient, event_id=None, drug_name="Metformin", strength="500 mg", quantity=1, timestamp=None):
        return self.post(
            patient,
            "/scans",
            {
                "event_id": event_id or str(uuid.uuid4()),
                "user_id": patient["id"],
                "drug_name": drug_name,
                "strength": strength,
                "quantity": quantity,
                "timestamp": timestamp or clock.utcnow().isoformat().replace("+00:00", "Z"),
            },
        )


@pytest.fixture
def api(client):
    return Api(client)
