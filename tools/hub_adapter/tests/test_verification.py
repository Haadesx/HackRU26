"""Verification block + dosage form/unit tests for the fallback hub adapter.

Locks the six backend statuses (mirroring backend/app/hub/verify.py) and the rule
that completing a scan must never invent a dosage form or a "tablet" unit.
"""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tools.hub_adapter import app as hub
from tools.hub_adapter import verification

PNG = b"\x89PNG\r\n\x1a\nstub-photo"

STATE = {
    "patient": {"name": "Test", "caregiver": "Test"},
    "settings": {},
    "medications": [
        {"id": 1, "name": "Lisinopril", "strength": "10 mg", "dose_amount": 1,
         "schedule_times": ["08:00"], "quantity_start": 30, "pills_left": 30},
        {"id": 2, "name": "Metformin", "strength": "500 mg", "dose_amount": 1,
         "schedule_times": ["08:00", "20:00"], "quantity_start": 60, "pills_left": 60},
    ],
    "doses": [],
    "scans": [],
    "reminders": [],
    "alerts": [],
}

COMPLETE_VALUES = {
    "name": "Metformin",
    "strength": "500 mg",
    "dose_amount": "1",
    "schedule_times": "08:00, 20:00",
    "quantity_start": "60",
}


def _field(value, confidence=0.95):
    return {"value": value, "confidence": confidence if value else 0.0, "source": "ocr" if value else "none"}


def _strength_field(text):
    if not text:
        return {"value": None, "unit": None, "confidence": 0.0, "source": "none"}
    value, _, unit = text.partition(" ")
    return {"value": float(value), "unit": unit or None, "confidence": 0.95, "source": "ocr"}


def make_result(name="Metformin", strength="500 mg", form="tablet", form_conf=0.9, unit="tablet", unit_conf=0.9):
    return {
        "status": "ok",
        "medication": {
            "name": _field(name),
            "strength": _strength_field(strength),
            "form": {
                "value": form,
                "confidence": form_conf if form else 0.0,
                "source": "ocr" if (form and form_conf >= 0.5) else "none",
            },
        },
        "instructions": {
            "dose": {
                "quantity": 1,
                "unit": unit,
                "confidence": unit_conf if unit else 0.0,
                "source": "ocr" if (unit and unit_conf >= 0.5) else "none",
            },
            "raw_text": "Take 1 by mouth",
        },
    }


@pytest.fixture
def state():
    return copy.deepcopy(STATE)


@pytest.fixture
def client(monkeypatch, tmp_path, state):
    monkeypatch.setattr(hub, "STATE", state)
    monkeypatch.setattr(hub, "SCAN_DIR", tmp_path)
    monkeypatch.setattr(hub, "_save", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hub, "backend", lambda: None)  # demo mode
    return TestClient(hub.app)


def _scan(client, monkeypatch, result):
    monkeypatch.setattr(hub, "run_inference", lambda photos: result)
    response = client.post("/scans", files={"photo": ("photo.png", PNG, "image/png")})
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------- six statuses


def test_uncertain_when_name_unreadable(client, monkeypatch):
    body = _scan(client, monkeypatch, make_result(name=None))
    verification_block = body["verification"]
    assert verification_block["status"] == "uncertain"
    assert verification_block["can_log"] is False
    assert verification_block["message"] == verification.UNCERTAIN_MESSAGE


def test_wrong_medication_for_untracked_name(client, monkeypatch):
    body = _scan(client, monkeypatch, make_result(name="Furosemide", strength="40 mg"))
    verification_block = body["verification"]
    assert verification_block["status"] == "wrong_medication"
    assert verification_block["can_log"] is False
    assert verification_block["scanned"]["name"] == "Furosemide"
    assert "isn't a medication you're tracking" in verification_block["message"]


def test_strength_mismatch(client, monkeypatch):
    body = _scan(client, monkeypatch, make_result(name="Metformin", strength="1000 mg"))
    verification_block = body["verification"]
    assert verification_block["status"] == "strength_mismatch"
    assert verification_block["medication"]["id"] == 2
    assert "1000 mg" in verification_block["message"] and "500 mg" in verification_block["message"]


def test_already_taken_when_dose_logged_within_six_hours(client, monkeypatch, state):
    state["doses"].append({
        "id": 1, "medication_id": 2,
        "taken_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    })
    body = _scan(client, monkeypatch, make_result(name="Metformin"))
    verification_block = body["verification"]
    assert verification_block["status"] == "already_taken"
    assert verification_block["can_log"] is False
    assert "don't take another dose" in verification_block["message"]


def test_due_now_when_scheduled_within_window(client, monkeypatch, state):
    fixed = datetime(2026, 10, 11, 8, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(verification, "_now", lambda: fixed)
    state["medications"][1]["schedule_times"] = ["08:00"]
    body = _scan(client, monkeypatch, make_result(name="Metformin"))
    verification_block = body["verification"]
    assert verification_block["status"] == "due_now"
    assert verification_block["can_log"] is True
    assert verification_block["due_local"] == "08:00"


def test_not_due_with_next_time(client, monkeypatch, state):
    fixed = datetime(2026, 10, 11, 8, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(verification, "_now", lambda: fixed)
    state["medications"][1]["schedule_times"] = ["20:00"]
    body = _scan(client, monkeypatch, make_result(name="Metformin"))
    verification_block = body["verification"]
    assert verification_block["status"] == "not_due"
    assert verification_block["can_log"] is False
    assert verification_block["due_local"] == "20:00"
    assert "isn't due yet" in verification_block["message"]


def test_fuzzy_name_match_accepts_minor_ocr_noise():
    match = verification._match_tracked([{"id": 7, "name": "Metformin"}], "metform1n")
    assert match is not None and match["id"] == 7


class _FakeStore:
    def __init__(self, remote):
        self.remote = remote

    def build_state(self, local):
        return self.remote


def test_verification_uses_backend_state_in_backend_mode(client, monkeypatch, state):
    state["medications"] = []  # local state knows nothing; backend supplies the medication
    remote = {"medications": [{"id": 99, "name": "Metformin", "strength": "500 mg", "schedule_times": ["08:00"]}], "doses": []}
    monkeypatch.setattr(hub, "backend", lambda: _FakeStore(remote))
    body = _scan(client, monkeypatch, make_result(name="Metformin"))
    assert body["verification"]["status"] in ("due_now", "not_due")
    assert body["verification"]["medication"]["id"] == 99


def test_verification_falls_back_to_local_state_when_backend_errors(client, monkeypatch, state):
    class _Broken:
        def build_state(self, local):
            raise RuntimeError("backend down")

    monkeypatch.setattr(hub, "backend", lambda: _Broken())
    body = _scan(client, monkeypatch, make_result(name="Metformin"))
    assert body["verification"]["status"]
    assert body["verification"]["medication"]["id"] == 2


# ------------------------------------------------- verification on start/photo/get


def test_verification_on_start_photo_and_get(client, monkeypatch, state):
    fixed = datetime(2026, 10, 11, 8, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(verification, "_now", lambda: fixed)
    state["medications"][1]["schedule_times"] = ["08:00"]
    monkeypatch.setattr(hub, "run_inference", lambda photos: make_result(name="Metformin"))

    start = client.post("/scans", files={"photo": ("photo.png", PNG, "image/png")}).json()
    assert start["verification"]["status"] == "due_now"
    scan_id = start["id"]

    photo = client.post(f"/scans/{scan_id}/photos", files={"photo": ("photo.png", PNG, "image/png")}).json()
    assert photo["verification"]["status"] == "due_now"

    got = client.get(f"/scans/{scan_id}").json()
    assert got["verification"]["status"] == "due_now"


# ------------------------------------------------- form/unit storage + complete


def test_scan_stores_inferred_form_and_unit(client, monkeypatch):
    body = _scan(client, monkeypatch, make_result(form="capsule", unit="capsule"))
    assert body["dosage_form"] == "capsule"
    assert body["dose_unit"] == "capsule"


def test_complete_capsule_uses_inferred_form(client, monkeypatch):
    monkeypatch.setattr(hub, "run_inference", lambda photos: make_result(form="capsule", unit="capsule"))
    start = client.post("/scans", files={"photo": ("photo.png", PNG, "image/png")}).json()
    response = client.post(f"/scans/{start['id']}/complete", json=COMPLETE_VALUES)
    assert response.status_code == 200, response.text
    body = response.json()
    medication = body["medication"]
    assert medication["dosage_form"] == "capsule"
    assert medication["dose_unit"] == "capsule"
    assert body["warnings"] == []
    assert "tablet" not in medication["instructions"].lower()


def test_complete_unknown_form_warns_and_never_invents_tablet(client, monkeypatch):
    monkeypatch.setattr(hub, "run_inference", lambda photos: make_result(form=None, unit=None))
    start = client.post("/scans", files={"photo": ("photo.png", PNG, "image/png")}).json()
    response = client.post(f"/scans/{start['id']}/complete", json=COMPLETE_VALUES)
    assert response.status_code == 200, response.text
    body = response.json()
    medication = body["medication"]
    assert medication["dosage_form"] is None
    assert medication["dose_unit"] == "unit"
    assert body["warnings"] and body["warnings"][0]["field"] == "dosage_form"
    assert "wasn't readable" in body["warnings"][0]["message"]
    assert "tablet" not in json.dumps(medication).lower()


def test_complete_ignores_low_confidence_form(client, monkeypatch):
    # Both form and dose unit are weak/none: the form must not be invented from either.
    monkeypatch.setattr(hub, "run_inference", lambda photos: make_result(form="tablet", form_conf=0.2, unit=None))
    start = client.post("/scans", files={"photo": ("photo.png", PNG, "image/png")}).json()
    response = client.post(f"/scans/{start['id']}/complete", json=COMPLETE_VALUES)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["medication"]["dosage_form"] is None
    assert body["medication"]["dose_unit"] == "unit"
    assert body["warnings"]


def test_complete_keeps_readable_dose_unit_when_form_is_unknown(client, monkeypatch):
    # Unit "tablet" is fine here: it was actually read from the dose unit, not invented.
    monkeypatch.setattr(hub, "run_inference", lambda photos: make_result(form="tablet", form_conf=0.2, unit="tablet"))
    start = client.post("/scans", files={"photo": ("photo.png", PNG, "image/png")}).json()
    body = client.post(f"/scans/{start['id']}/complete", json=COMPLETE_VALUES).json()
    assert body["medication"]["dosage_form"] is None
    assert body["medication"]["dose_unit"] == "tablet"
    assert body["warnings"]
