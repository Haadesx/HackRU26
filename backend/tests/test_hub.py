"""/hub compatibility layer vs frontend/docs/api-contract.md (and the UI's fixtures)."""

import io
import json
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import T0, set_now
from sqlalchemy import select

from app.extensions import db
from app.hub import labels
from app.jobs import tasks
from app.models import DoseEvent, Medication, Prescription, PrescriptionItem, Reminder

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "docs" / "fixtures"
HUB_EMAIL = "hub.patient@example.com"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
LOSARTAN_LABEL = (
    "LOSARTAN POTASSIUM 25 mg TABLETS\nTake 1 tablet by mouth once daily\nQTY: 30   Refills: 2\n"
    "CVS Pharmacy (732) 555-0123\nDr. Patel"
)


def inference(name="Losartan", name_conf=0.95, strength=(25, "mg"), strength_conf=0.92, dose=1, text=LOSARTAN_LABEL, status="ok", guidance=None, form=None, form_conf=0.85, form_source=None, dose_unit=None, frequency="once daily"):
    return {
        "status": status,
        "frame_quality": {"acceptable": status != "needs_rescan", "score": 0.9, "guidance": guidance or []},
        "label": {"detected": True, "confidence": 0.9, "text": text},
        "medication": {
            "name": {"value": name, "confidence": name_conf, "source": "ocr"},
            "strength": {"value": strength[0], "unit": strength[1], "confidence": strength_conf, "source": "ocr"} if strength else {"value": None, "unit": None, "confidence": 0, "source": "none"},
            "form": {"value": form, "confidence": form_conf if form else 0, "source": (form_source or ("ocr" if form else "none"))},
        },
        "instructions": {
            "raw_text": f"Take 1 tablet by mouth {frequency}",
            "parsed": [{"kind": "frequency", "text": frequency}],
            "dose": {"quantity": dose, "unit": dose_unit, "confidence": 0.9, "source": "ocr"} if dose else None,
        },
    }


class FakeInference:
    def __init__(self, monkeypatch):
        self.queue, self.calls = [], []
        monkeypatch.setattr(labels.http, "post", self._post)

    def _post(self, url, files=None, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data})
        body = self.queue.pop(0)
        if isinstance(body, Exception):
            raise body

        class R:
            status_code = 200

            def json(self_inner):
                return body

        return R()


@pytest.fixture
def hub(api, client):
    p = api.register("patient", name="Rosa Diaz", email=HUB_EMAIL)
    api.active_metformin(p)  # breakfast 08:00 + dinner 19:00, 60 tablets

    class Hub:
        patient = p

        def get(self, path, **kw):
            return client.get(f"/hub{path}", **kw)

        def post(self, path, json=None, **kw):
            return client.post(f"/hub{path}", json=json, **kw)

        def put(self, path, json):
            return client.put(f"/hub{path}", json=json)

        def patch(self, path, json):
            return client.patch(f"/hub{path}", json=json)

        def delete(self, path):
            return client.delete(f"/hub{path}")

        def photo(self, path):
            return client.post(f"/hub{path}", data={"photo": (io.BytesIO(JPEG), "label.jpg", "image/jpeg")}, content_type="multipart/form-data")

        def state(self):
            r = client.get("/hub/state")
            assert r.status_code == 200, r.get_json()
            return r.get_json()

        def med(self, name="Metformin"):
            return next(m for m in self.state()["medications"] if m["name"] == name)

    return Hub()


def _keys(obj):
    return set(obj.keys())


def test_state_matches_ui_fixture_shape(hub):
    fixture = json.loads((FIXTURES / "state.json").read_text())
    state = hub.state()
    assert _keys(fixture) <= _keys(state)
    med = state["medications"][0]
    fixture_med = {k for k in fixture["medications"][0] if k != "otc"}
    assert fixture_med <= _keys(med)
    assert med["name"] == "Metformin" and med["strength"] == "500 mg"
    assert med["schedule_times"] == ["08:00", "19:00"] and med["doses_per_day"] == 2
    assert med["dose_amount"] == 1 and med["pills_left"] == 60 and med["quantity_start"] == 60
    assert med["refills_remaining"] == 2 and isinstance(med["id"], int)
    assert _keys(fixture["settings"]) <= _keys(state["settings"])
    assert state["patient"]["name"] == "Rosa" and state["hub"] == {"connected": True}
    assert hub.get("/health").get_json() == {"ok": True}


def test_log_dose_and_readable_errors(hub):
    med = hub.med()
    set_now(T0 + timedelta(hours=1, minutes=5))  # 08:05 local
    r = hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"})
    assert r.status_code == 200, r.get_json()
    state = r.get_json()
    m = next(x for x in state["medications"] if x["id"] == med["id"])
    assert m["pills_left"] == 59
    dose = state["doses"][-1]
    assert (dose["medication_id"], dose["slot"], dose["date"], dose["method"]) == (med["id"], "08:00", "2026-10-12", "dashboard")
    assert isinstance(dose["id"], int)
    # Next slot (19:00) isn't open yet
    r = hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"})
    assert r.status_code == 409 and r.get_json() == {"detail": "The 19:00 dose of Metformin can be logged from 18:30."}
    r = hub.post(f"/medications/{med['id']}/doses", {"slot": "08:00"})
    assert r.status_code == 409 and "already logged" in r.get_json()["detail"]
    assert hub.post("/medications/9999/doses", {}).get_json() == {"detail": "That medication no longer exists."}


def test_counts_alert_once_and_refill_clears(hub, monkeypatch):
    from app.services.channels import sms as sms_channel

    texts = []
    monkeypatch.setattr(sms_channel, "configured", lambda: True)
    monkeypatch.setattr(sms_channel, "send", lambda to, body: texts.append((to, body)) or "SM")
    hub.put("/settings", {**hub.state()["settings"], "caregivers": [
        {"name": "Elena", "phone": "(732) 555-0187", "scope": "all", "you": True},
        {"name": "Marco", "phone": "(908) 555-0142", "scope": "refills"},
    ]})
    med = hub.med()
    r = hub.post(f"/medications/{med['id']}/counts", {"count": 5})
    alerts = r.get_json()["alerts"]
    assert [(a["type"], a["message"]) for a in alerts] == [("low_3", "Rosa has about 2 days of Metformin left.")]
    hub.state()
    hub.state()
    assert len(hub.state()["alerts"]) == 1  # once per threshold per bottle
    assert sorted(t[0] for t in texts) == ["+17325550187", "+19085550142"]
    assert hub.post(f"/medications/{med['id']}/counts", {"count": 3, "confidence": 0.5}).status_code == 422

    state = hub.post(f"/medications/{med['id']}/refill").get_json()
    m = next(x for x in state["medications"] if x["id"] == med["id"])
    assert m["pills_left"] == 65 and m["refills_remaining"] == 1 and m["fill_date"] == "2026-10-12"
    assert state["alerts"] == []


def test_patch_medication_and_no_refills_alert(hub):
    med = hub.med()
    state = hub.patch(f"/medications/{med['id']}", {"refills_remaining": 0, "prescriber": "Dr. Okafor", "pharmacy_phone": "(732) 555-0123"}).get_json()
    m = next(x for x in state["medications"] if x["id"] == med["id"])
    assert m["prescriber"] == "Dr. Okafor" and m["refills_remaining"] == 0 and m["confidence"] == {}
    assert state["alerts"][0]["type"] == "no_refills"
    assert "Dr. Okafor needs to send a new prescription" in state["alerts"][0]["message"]
    assert hub.patch(f"/medications/{med['id']}", {"quantity_start": "abc"}).status_code == 422


def test_scan_two_photos_merge_and_complete(hub, monkeypatch, ctx):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name_conf=0.6, text=""), inference()]
    r = hub.photo("/scans")
    assert r.status_code == 200, r.get_json()
    scan = r.get_json()
    assert scan["status"] == "reading" and scan["photos"] == 1
    assert scan["fields"]["name"] == {"value": "Losartan", "state": "unsure"}
    assert scan["fields"]["quantity_start"]["state"] == "missing"
    assert scan["history"][0]["step"] == "Scanned"
    assert json.loads(fake.calls[0]["data"]["hints"])["known_candidates"][0]["name"] == "Metformin"

    scan = hub.photo(f"/scans/{scan['id']}/photos").get_json()
    f = scan["fields"]
    assert scan["photos"] == 2 and scan["status"] == "reading"
    assert f["name"] == {"value": "Losartan", "state": "filled"}
    assert f["strength"] == {"value": "25 mg", "state": "filled"}
    assert f["dose_amount"] == {"value": "1", "state": "filled"}
    assert f["schedule_times"] == {"value": "08:00", "state": "unsure"}  # converted from "once daily"
    assert f["quantity_start"] == {"value": "30", "state": "unsure"}
    assert f["refills_remaining"] == {"value": "2", "state": "unsure"}
    assert f["pharmacy_name"] == {"value": "CVS Pharmacy", "state": "unsure"}
    assert f["pharmacy_phone"] == {"value": "(732) 555-0123", "state": "unsure"}
    assert f["prescriber"] == {"value": "Dr. Patel", "state": "unsure"}

    values = {k: v["value"] for k, v in f.items()}
    values["dosage_form"] = "tablet"  # caregiver confirms the form the label didn't state
    r = hub.post(f"/scans/{scan['id']}/complete", values)
    assert r.status_code == 200, r.get_json()
    med = r.get_json()["medication"]
    assert (med["name"], med["strength"], med["schedule_times"], med["pills_left"], med["refills_remaining"]) == ("Losartan", "25 mg", ["08:00"], 30, 2)
    assert med["instructions"] == "Take 1 tablet by mouth once daily"
    assert med["confidence"] == {"prescriber": "unsure", "pharmacy_name": "unsure", "pharmacy_phone": "unsure", "refills_remaining": "unsure"}
    state = hub.state()
    assert {m["name"] for m in state["medications"]} == {"Metformin", "Losartan"}
    assert next(s for s in state["scans"] if s["id"] == scan["id"])["status"] == "complete"
    assert hub.post(f"/scans/{scan['id']}/complete", values).status_code == 409
    # Losartan doses were generated; Metformin's history and stock carried over
    doses = db.session.scalars(select(Prescription.version)).all()
    assert sorted(doses) == [1, 2]
    assert next(m for m in state["medications"] if m["name"] == "Metformin")["pills_left"] == 60


def test_label_meta_v13_preferred_over_regex(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    body = inference()
    body["label_meta"] = {
        "quantity_start": {"value": "90", "confidence": 0.93, "source": "ocr"},
        "refills_remaining": {"value": "3", "confidence": 0.9, "source": "ocr"},
        "pharmacy_name": {"value": "Walgreens #4412", "confidence": 0.88, "source": "ocr"},
        "pharmacy_phone": {"value": None, "confidence": 0, "source": "none"},
        "prescriber": {"value": "Dr. Okafor", "confidence": 0.6, "source": "ocr"},
        "schedule_times": {"value": "08:00, 20:00", "confidence": 0.7, "source": "ocr"},
    }
    fake.queue = [body]
    f = hub.photo("/scans").get_json()["fields"]
    assert f["quantity_start"] == {"value": "90", "state": "filled"}
    assert f["refills_remaining"] == {"value": "3", "state": "filled"}
    assert f["pharmacy_name"] == {"value": "Walgreens #4412", "state": "filled"}
    assert f["prescriber"] == {"value": "Dr. Okafor", "state": "unsure"}
    assert f["schedule_times"] == {"value": "08:00, 20:00", "state": "unsure"}
    assert f["pharmacy_phone"] == {"value": "(732) 555-0123", "state": "unsure"}  # regex fallback fills the gap


def test_interval_cadence_never_invents_schedule(hub, monkeypatch):
    """"every 8 hours" is not day-anchored: the hub must not convert it to fixed times."""
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(frequency="every 8 hours")]
    fields = hub.photo("/scans").get_json()["fields"]
    assert fields["schedule_times"] == {"value": "", "state": "missing"}


def test_day_anchored_frequency_still_converts_as_unsure(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(frequency="twice daily")]
    fields = hub.photo("/scans").get_json()["fields"]
    assert fields["schedule_times"] == {"value": "08:00, 20:00", "state": "unsure"}


def test_complete_preserves_capsule_form(hub, ctx, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Amoxicillin", form="capsule", dose_unit="capsule")]
    scan = hub.photo("/scans").get_json()
    values = {k: v["value"] for k, v in scan["fields"].items()}
    r = hub.post(f"/scans/{scan['id']}/complete", values)
    assert r.status_code == 200, r.get_json()
    med = db.session.scalar(select(Medication).where(Medication.name == "Amoxicillin"))
    assert med is not None and med.dosage_form == "capsule"
    item = db.session.scalar(select(PrescriptionItem).where(PrescriptionItem.medication_id == med.id))
    assert item is not None and item.dose_unit == "capsule"


def test_complete_unknown_form_requires_caregiver_choice(hub, ctx, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Furosemide", form=None, dose_unit=None)]
    scan = hub.photo("/scans").get_json()
    values = {k: v["value"] for k, v in scan["fields"].items()}
    r = hub.post(f"/scans/{scan['id']}/complete", values)
    assert r.status_code == 422 and "tablets or capsules" in r.get_json()["detail"]
    assert db.session.scalar(select(Medication).where(Medication.name == "Furosemide")) is None  # nothing saved
    r = hub.post(f"/scans/{scan['id']}/complete", {**values, "dosage_form": "tablet"})
    assert r.status_code == 200, r.get_json()
    med = db.session.scalar(select(Medication).where(Medication.name == "Furosemide"))
    assert med is not None and med.dosage_form == "tablet"  # caregiver-confirmed, never assumed


def test_vlm_zero_confidence_form_is_not_trusted(hub, ctx, monkeypatch):
    """The VLM can guess "tablet" with confidence 0 for a label that never states a form."""
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Tamsulosin", form="tablet", form_conf=0.0, form_source="vlm", dose_unit=None)]
    scan = hub.photo("/scans").get_json()
    assert "dosage_form" not in scan  # evidence floor dropped the guess
    values = {k: v["value"] for k, v in scan["fields"].items()}
    r = hub.post(f"/scans/{scan['id']}/complete", values)
    assert r.status_code == 422  # must ask the caregiver instead of trusting the guess
    r = hub.post(f"/scans/{scan['id']}/complete", {**values, "dosage_form": "capsule"})
    assert r.status_code == 200, r.get_json()
    med = db.session.scalar(select(Medication).where(Medication.name == "Tamsulosin"))
    assert med is not None and med.dosage_form == "capsule"  # caregiver's choice, not the VLM's "tablet"


def test_name_taken_from_label_when_ocr_name_is_weak(hub, monkeypatch):
    """OCR read FLUOXETINE but its lexicon doesn't know it, so it guessed 'DEMO' at 0.3.
    The hub uses the label text itself; no drug list (OpenFDA or otherwise) limits the name."""
    from app.services import openfda

    def no_network(*a, **kw):
        raise AssertionError("scan name extraction must not call OpenFDA")

    monkeypatch.setattr(openfda, "search", no_network)
    fake = FakeInference(monkeypatch)
    fake.queue = [
        inference(name="DEMO", name_conf=0.3, strength=(20, "mg"),
                  text="DEMO PHARMACY (555) 010-2030\nFLUOXETINE 20 mg CAPSULES\nTake 1 capsule by mouth once daily"),
        inference(name=None, text="MEFTAL-SPAS\nEach tablet contains\nDicyclomine Hydrochloride 10mg"),
        inference(name=None, text="SOMEBRAND 5 mg TABLETS"),
        inference(name=None, text="Take with food\nKeep out of reach of children"),
    ]
    names = [hub.photo("/scans").get_json()["fields"]["name"] for _ in range(4)]
    assert names[0] == {"value": "Fluoxetine", "state": "unsure"}
    assert names[1] == {"value": "Dicyclomine Hydrochloride", "state": "unsure"}
    assert names[2] == {"value": "Somebrand", "state": "unsure"}  # any name, any source
    assert names[3]["state"] == "missing"  # no strength line -> nothing guessed


def test_name_from_label_rules():
    assert labels.name_from_label("Take 1 tablet\nLISINOPRIL 10 mg TABLETS") == "Lisinopril"
    assert labels.name_from_label("Each tablet contains Mefenamic Acid 250mg") == "Mefenamic Acid"
    assert labels.name_from_label("Low Dose\nAspirin\n81mg Delayed-Release Tablets") == "Aspirin"  # line above
    assert labels.name_from_label("Take 1 tablet each day for pain relief\n250mg") is None  # long line above: not a name
    assert labels.name_from_label("") is None


def test_low_confidence_values_are_kept_as_unsure(hub, monkeypatch):
    """A value read at any confidence is shown (unsure) so the caregiver can confirm it; only nothing-read is missing."""
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Aspirin", name_conf=0.3, strength=(81, "mg"), text="Aspirin\nLow Dose")]
    f = hub.photo("/scans").get_json()["fields"]
    assert f["name"] == {"value": "Aspirin", "state": "unsure"}
    assert labels.state_for(0.2, "x") == "unsure" and labels.state_for(0.9, "x") == "filled" and labels.state_for(0.9, "") == "missing"


def test_scan_rescan_guidance_and_inference_down(hub, monkeypatch):
    import requests

    fake = FakeInference(monkeypatch)
    fake.queue = [inference(status="needs_rescan", guidance=["Move closer to the label"]), requests.ConnectionError("down")]
    scan = hub.photo("/scans").get_json()
    assert scan["guidance"] == ["Move closer to the label"]
    assert all(v["state"] == "missing" for v in scan["fields"].values())
    r = hub.photo(f"/scans/{scan['id']}/photos")
    assert r.status_code == 503 and "label reader isn't reachable" in r.get_json()["detail"]


def test_missing_details_escalate_to_caregiver(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    no_qty = LOSARTAN_LABEL.replace("QTY: 30", "")
    fake.queue = [inference(text=no_qty), inference(text=no_qty)]
    scan = hub.photo("/scans").get_json()
    scan = hub.photo(f"/scans/{scan['id']}/photos").get_json()
    assert scan["status"] == "asking_patient"
    assert "amount in the bottle" in scan["history"][-1]["detail"]
    set_now(T0 + timedelta(minutes=4))
    s = next(x for x in hub.state()["scans"] if x["id"] == scan["id"])
    assert s["status"] == "needs_caregiver" and s["history"][-1]["step"] == "Sent to you"


def test_complete_validation_and_manual(hub):
    scan = hub.post("/scans", {"manual": True}).get_json()
    assert scan["manual"] is True and scan["photos"] == 0 and len(scan["fields"]) == 9
    base = {"name": "Losartan", "strength": "25 mg", "dose_amount": "1", "schedule_times": "08:00", "quantity_start": "30",
            "refills_remaining": "", "pharmacy_name": "", "pharmacy_phone": "", "prescriber": "", "dosage_form": "tablet"}
    r = hub.post(f"/scans/{scan['id']}/complete", {**base, "quantity_start": ""})
    assert r.status_code == 422 and r.get_json()["detail"] == "Tablets in the bottle is required."
    r = hub.post(f"/scans/{scan['id']}/complete", {**base, "schedule_times": "8am"})
    assert r.status_code == 422 and "24-hour" in r.get_json()["detail"]
    r = hub.post(f"/scans/{scan['id']}/complete", {**base, "name": "metformin", "strength": "500mg"})
    assert r.status_code == 409 and "already being tracked" in r.get_json()["detail"]
    r = hub.post(f"/scans/{scan['id']}/complete", {**base, "schedule_times": "08:00, 12:30, 8:00"})
    assert r.status_code == 200, r.get_json()
    med = r.get_json()["medication"]
    assert med["schedule_times"] == ["08:00", "12:30"] and med["refills_remaining"] is None
    assert hub.delete(f"/scans/{scan['id']}").status_code == 200


def test_stop_tracking_keeps_history(hub, ctx):
    med = hub.med()
    set_now(T0 + timedelta(hours=1, minutes=5))
    hub.post(f"/medications/{med['id']}/doses", {})
    state = hub.delete(f"/medications/{med['id']}").get_json()
    assert state["medications"] == []
    assert db.session.scalar(select(Prescription.status)) == "superseded"
    r = hub.get("/adherence?month=2026-10").get_json()
    assert next(d for d in r["days"] if d["date"] == "2026-10-12")["due"] == 1  # taken dose still counts


def test_adherence_month(hub, ctx):
    later = T0 + timedelta(days=1, hours=4)  # Tue 11:00 local
    set_now(later)
    tasks.mark_missed_doses(later)
    r = hub.get("/adherence?month=2026-10")
    assert r.status_code == 200
    body = r.get_json()
    assert body["year"] == 2026 and body["month"] == 9 and len(body["days"]) == 31
    day12 = next(d for d in body["days"] if d["date"] == "2026-10-12")
    assert (day12["due"], day12["missed"], day12["future"]) == (2, 2, False)
    assert {x["slot"] for x in day12["missedList"]} == {"08:00", "19:00"}
    day13 = next(d for d in body["days"] if d["date"] == "2026-10-13")
    assert (day13["due"], day13["missed"]) == (1, 1)
    assert next(d for d in body["days"] if d["date"] == "2026-10-20")["future"] is True
    assert (body["due"], body["taken"], body["missed"]) == (3, 0, 3)
    assert hub.get("/adherence?month=oct").status_code == 422


def test_settings_validation_delete_all_events_remind(hub, ctx):
    s = hub.state()["settings"]
    bad = {**s, "thresholds": {"first": 3, "second": 5, "urgent": 7}}
    assert hub.put("/settings", bad).status_code == 422
    assert hub.put("/settings", {**s, "caregivers": [{"name": "Elena", "phone": "12", "scope": "all"}]}).status_code == 422
    saved = hub.put("/settings", {**s, "alert_wrong_bottle": True, "caregivers": [{"name": "Elena", "phone": "(732) 555-0187", "scope": "all", "you": True}]}).get_json()
    assert saved["settings"]["alert_wrong_bottle"] is True and saved["settings"]["caregivers"][0]["id"] == 1
    assert saved["patient"]["caregiver"] == "Elena"

    state = hub.post("/events", {"type": "wrong_bottle", "message": "Rosa picked up Metformin when Lisinopril was due."}).get_json()
    assert state["events"][0]["type"] == "wrong_bottle"
    med = state["medications"][0]
    state = hub.post(f"/medications/{med['id']}/remind", {"slot": "08:00"}).get_json()
    assert state["reminders"] == [{"medication_id": med["id"], "slot": "08:00", "date": "2026-10-12", "sent_at": state["reminders"][0]["sent_at"]}]
    assert "Elena is reminding you" in db.session.scalar(select(Reminder.body).where(Reminder.kind == "dose_followup", Reminder.dose_event_id.is_(None)))

    export = hub.get("/export")
    assert export.status_code == 200 and "attachment" in export.headers["Content-Disposition"]

    state = hub.delete("/data").get_json()
    assert state["medications"] == [] and state["doses"] == [] and state["events"] == []
    assert state["settings"]["caregivers"][0]["name"] == "Elena"


def test_missed_dose_texts_contacts(hub, monkeypatch, ctx):
    from app.services.channels import sms as sms_channel

    texts = []
    monkeypatch.setattr(sms_channel, "configured", lambda: True)
    monkeypatch.setattr(sms_channel, "send", lambda to, body: texts.append(body) or "SM")
    hub.put("/settings", {**hub.state()["settings"], "caregivers": [{"name": "Elena", "phone": "(732) 555-0187", "scope": "all"}, {"name": "Marco", "phone": "(908) 555-0142", "scope": "refills"}]})
    at = T0 + timedelta(hours=3, minutes=1)
    set_now(at)
    tasks.mark_missed_doses(at)
    assert texts == ["MedCheck: Rosa hasn't taken the 08:00 dose of Metformin 500 mg."]  # refills-only contact not texted


def test_hub_disabled_returns_404(app):
    from app import create_app

    off = create_app({"TESTING": True, "HUB_ENABLED": False})
    assert off.test_client().get("/hub/state").status_code == 404


def test_hub_patient_missing_is_readable(client):
    r = client.get("/hub/state")
    assert r.status_code == 503 and "Run `python -m scripts.seed`" in r.get_json()["detail"]


# ---------- scan-vs-prescription verification ----------

METFORMIN_SCAN = dict(name="Metformin", strength=(500, "mg"))


def test_verification_due_now_offers_explicit_log(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))  # 08:00 local — breakfast window is open
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "due_now" and v["can_log"] is True
    assert v["medication"]["name"] == "Metformin" and v["dose_event_id"]
    assert "never records a dose" in v["message"]


def test_verification_already_taken_blocks_second_log(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    med = hub.med("Metformin")
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200
    set_now(T0 + timedelta(hours=12, minutes=5))  # 19:05 — dinner window open
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200
    set_now(T0 + timedelta(hours=12, minutes=20))  # both doses of the day logged
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "already_taken" and v["can_log"] is False
    assert v["taken_local"]
    # the backend re-checks eligibility: another log is refused even though the scan looked positive
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 409


def test_verification_not_due_when_window_closed(hub, monkeypatch):
    set_now(T0 - timedelta(hours=2))  # 05:00 local — before the breakfast window
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "not_due" and v["can_log"] is False
    assert v["due_local"] == "08:00"


def test_verification_wrong_medication(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference()]  # Losartan 25 mg — not tracked
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "wrong_medication" and v["can_log"] is False


def test_verification_strength_mismatch(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(1000, "mg"))]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "strength_mismatch" and v["can_log"] is False
    assert "1000 mg" in v["message"]


def test_verification_uncertain_without_readable_name(hub):
    scan = hub.post("/scans", {"manual": True}).get_json()
    assert scan["verification"]["status"] == "uncertain"
    assert scan["verification"]["can_log"] is False


def test_verification_morning_taken_evening_upcoming_is_not_due(hub, monkeypatch):
    """A dose taken hours ago must not hide the next scheduled dose."""
    set_now(T0 + timedelta(hours=1))  # 08:00 — breakfast taken now
    med = hub.med("Metformin")
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200
    set_now(T0 + timedelta(hours=9))  # 16:00 — before the 19:00 dinner window
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "not_due" and v["can_log"] is False
    assert v["due_local"] == "19:00"


def test_verification_recent_morning_dose_does_not_hide_evening(hub, monkeypatch):
    """Even inside the recent-dose window, a later dose today stays visible."""
    set_now(T0 + timedelta(hours=1))
    med = hub.med("Metformin")
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200
    set_now(T0 + timedelta(hours=5))  # 12:00 — only 4h after the breakfast dose
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "not_due" and v["can_log"] is False
    assert v["due_local"] == "19:00"
    assert "already logged" in v["message"]


# ---------- verification: fail-closed evidence gates ----------


def test_verification_missing_strength_fails_closed(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", strength=None)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False
    assert "strength" in v["message"].lower()


def test_verification_unsure_strength_fails_closed(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(500, "mg"), strength_conf=0.6)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False


def test_verification_unsure_name_fails_closed(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", name_conf=0.6, strength=(500, "mg"))]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False


def test_verification_fuzzy_name_is_not_proof(hub, monkeypatch):
    """A close spelling is a candidate, not an identity."""
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformn", name_conf=0.95, strength=(500, "mg"))]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False
    assert "Metformin 500 mg" in v["message"]


def test_verification_exact_name_and_strength_matches(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "due_now"
    assert v["medication"] == {"id": hub.med()["id"], "name": "Metformin", "strength": "500 mg"}
    assert v["strength_match"] is True and v["matched"] == {"name": "exact", "strength": "exact"}


ADD_METFORMIN_1000 = {
    "name": "Metformin", "strength": "1000 mg", "dose_amount": "1",
    "schedule_times": "08:00", "quantity_start": "30", "dosage_form": "tablet",
}


def _add_second_strength(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(1000, "mg"))]
    sid = hub.photo("/scans").get_json()["id"]
    r = hub.post(f"/scans/{sid}/complete", ADD_METFORMIN_1000)
    assert r.status_code == 200, r.get_json()
    return fake


def test_verification_same_name_two_strengths_picks_matching(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = _add_second_strength(hub, monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(1000, "mg"))]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["medication"]["strength"] == "1000 mg"
    assert v["status"] in ("due_now", "not_due", "already_taken")
    fake.queue = [inference(name="Metformin", strength=(500, "mg"))]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["medication"]["strength"] == "500 mg"


def test_verification_strength_matching_neither_of_two(hub, monkeypatch):
    set_now(T0 + timedelta(hours=1))
    fake = _add_second_strength(hub, monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(750, "mg"))]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "strength_mismatch" and v["can_log"] is False
    assert "medication" not in v
    assert "1000 mg" in v["message"] and "500 mg" in v["message"]


def test_verification_ambiguous_candidates_fail_closed(monkeypatch):
    """Two tracked rows with the same name and strength: the evidence cannot pick one."""
    from types import SimpleNamespace

    from app.hub import state as hub_state
    from app.hub import verify

    med = SimpleNamespace(name="Metformin", strength="500 mg")
    rows = [(SimpleNamespace(id=1, medication=med), SimpleNamespace(id=1, medication=med)),
            (SimpleNamespace(id=2, medication=med), SimpleNamespace(id=2, medication=med))]
    monkeypatch.setattr(hub_state, "tracked", lambda patient: rows)
    patient = SimpleNamespace(id=1, timezone="America/New_York")
    scan = SimpleNamespace(fields={
        "name": {"value": "Metformin", "state": "filled"},
        "strength": {"value": "500 mg", "state": "filled"},
    })
    v = verify.scan_verification(patient, scan)
    assert v["status"] == "uncertain" and v["can_log"] is False
    assert "more than one" in v["message"]


def test_verification_never_records_a_dose(hub, ctx, monkeypatch):
    set_now(T0 + timedelta(hours=1))

    def taken_count():
        return len(db.session.scalars(
            select(DoseEvent).where(DoseEvent.patient_id == hub.patient["id"], DoseEvent.status.in_(("taken_on_time", "taken_late")))
        ).all())

    before = taken_count()
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "due_now" and v["can_log"] is True
    assert taken_count() == before


def test_stale_can_log_cannot_bypass_backend_eligibility(hub, monkeypatch):
    """A can_log from an earlier scan must not let a later confirm slip through."""
    set_now(T0 + timedelta(hours=1))
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(**METFORMIN_SCAN)]
    v = hub.photo("/scans").get_json()["verification"]
    assert v["status"] == "due_now" and v["can_log"] is True
    med_id = v["medication"]["id"]
    assert hub.post(f"/medications/{med_id}/doses", {"method": "dashboard"}).status_code == 200
    r = hub.post(f"/medications/{med_id}/doses", {"method": "dashboard"})
    assert r.status_code == 409  # fresh eligibility check, not the stale can_log
    fake.queue = [inference(**METFORMIN_SCAN)]
    v2 = hub.photo("/scans").get_json()["verification"]
    assert v2["status"] != "due_now" and v2["can_log"] is False


# ---------- dosage-form confirmation ----------

SCAN_BODY = {"name": "Metformin", "strength": "500 mg", "dose_amount": "1", "schedule_times": "08:00", "quantity_start": "30"}


ADD_FUROSEMIDE_20 = {
    "name": "Furosemide", "strength": "20 mg", "dose_amount": "1",
    "schedule_times": "08:00", "quantity_start": "30", "dosage_form": "capsule",
}


def test_complete_scan_requires_dosage_form_when_label_is_silent(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Furosemide", strength=(20, "mg"), form=None)]
    sid = hub.photo("/scans").get_json()["id"]
    r = hub.post(f"/scans/{sid}/complete", {k: v for k, v in ADD_FUROSEMIDE_20.items() if k != "dosage_form"})
    assert r.status_code == 422
    assert "tablets or capsules" in r.get_json()["detail"]
    r2 = hub.post(f"/scans/{sid}/complete", ADD_FUROSEMIDE_20)
    assert r2.status_code == 200, r2.get_json()
    assert r2.get_json()["medication"]["dosage_form"] == "capsule"
    detail = hub.get(f"/scans/{sid}").get_json()["history"][-1]["detail"]
    assert "(capsule, caregiver)" in detail


def test_complete_scan_uses_label_form_without_confirmation(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Lisinopril", strength=(10, "mg"), form="tablet")]
    sid = hub.photo("/scans").get_json()["id"]
    scan = hub.get(f"/scans/{sid}").get_json()
    assert scan["dosage_form"] == "tablet"
    r = hub.post(f"/scans/{sid}/complete", {**SCAN_BODY, "name": "Lisinopril", "strength": "10 mg"})
    assert r.status_code == 200
    assert r.get_json()["medication"]["dosage_form"] == "tablet"
    detail = hub.get(f"/scans/{sid}").get_json()["history"][-1]["detail"]
    assert "(tablet, label)" in detail


def test_complete_scan_rejects_conflicting_form_choice(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(500, "mg"), form="tablet")]
    sid = hub.photo("/scans").get_json()["id"]
    r = hub.post(f"/scans/{sid}/complete", {**SCAN_BODY, "dosage_form": "capsule"})
    assert r.status_code == 422
    assert "reads tablet" in r.get_json()["detail"]


def test_complete_scan_rejects_unsupported_unit(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(500, "mg"), form=None, dose_unit="ml")]
    sid = hub.photo("/scans").get_json()["id"]
    r = hub.post(f"/scans/{sid}/complete", SCAN_BODY)
    assert r.status_code == 422
    assert "tablet" in r.get_json()["detail"].lower()


def test_complete_scan_rejects_unsupported_form_choice(hub, monkeypatch):
    fake = FakeInference(monkeypatch)
    fake.queue = [inference(name="Metformin", strength=(500, "mg"), form=None)]
    sid = hub.photo("/scans").get_json()["id"]
    r = hub.post(f"/scans/{sid}/complete", {**SCAN_BODY, "dosage_form": "liquid"})
    assert r.status_code == 422
    assert "tablets and capsules" in r.get_json()["detail"]
