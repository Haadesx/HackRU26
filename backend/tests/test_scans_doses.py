import uuid
from datetime import timedelta

from conftest import T0, set_now
from sqlalchemy import func, select

from app.extensions import db
from app.models import DoseOutcome, InventoryTransaction, Reminder

BREAKFAST_0800 = T0 + timedelta(hours=1)  # 2026-10-12 08:00 EDT


def _setup(api, **kw):
    p = api.register("patient", name="Ada Patient")
    api.active_metformin(p, **kw)
    return p


def test_scan_matches_due_dose_without_changing_status(api):
    p = _setup(api)
    set_now(BREAKFAST_0800 + timedelta(minutes=5))
    r = api.scan(p, strength={"value": 500, "unit": "mg"})  # inference-contract shape
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["match_status"] == "matched"
    assert body["timing"] == "on_time" and body["quantity_check"] == "ok"
    assert body["medication"]["name"] == "Metformin" and body["medication"]["strength"] == "500 mg"
    assert body["dose_event"]["status"] == "pending"
    assert body["safety"]["ingestion_not_inferred"] is True


def test_scan_is_idempotent_on_event_id(api, ctx):
    p = _setup(api)
    set_now(BREAKFAST_0800)
    event_id = str(uuid.uuid4())
    first = api.scan(p, event_id=event_id).get_json()
    second = api.scan(p, event_id=event_id).get_json()
    assert first["replayed"] is False and second["replayed"] is True
    assert first["dose_event"]["id"] == second["dose_event"]["id"]
    from app.models import VisionObservation

    assert db.session.scalar(select(func.count()).select_from(VisionObservation)) == 1


def test_scan_fuzzy_name_and_no_match_and_wrong_strength(api):
    p = _setup(api)
    set_now(BREAKFAST_0800)
    assert api.scan(p, drug_name="METFORMIN HCl").get_json()["match_status"] == "matched"
    assert api.scan(p, drug_name="Metformn").get_json()["match_status"] == "matched"  # OCR typo
    assert api.scan(p, drug_name="Lisinopril", strength="10 mg").get_json()["match_status"] == "no_match"
    assert api.scan(p, strength="1000mg").get_json()["match_status"] == "no_match"


def test_scan_not_due_returns_next_dose(api):
    p = _setup(api)
    set_now(T0 + timedelta(hours=5))  # 12:00 local
    # Breakfast is past on_time_end but still confirmable until its confirm_deadline (19:00), so it matches as late.
    body = api.scan(p).get_json()
    assert body["match_status"] == "matched" and body["timing"] == "late"
    set_now(T0 - timedelta(hours=2))  # 05:00 local, before the breakfast window opens
    body = api.scan(p, timestamp=(T0 - timedelta(hours=2)).isoformat().replace("+00:00", "Z")).get_json()
    assert body["match_status"] == "not_due"
    assert body["next_dose"]["scheduled_at"].startswith("2026-10-12T12:00:00")


def test_scan_ambiguous_when_two_items_share_a_name(api):
    p = api.register("patient")
    rx = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [
        {"name": "Metformin", "strength": "500 mg", "dose_quantity": 1, "dose_unit": "tablet", "instructions": "With breakfast"},
        {"name": "Metformin", "strength": "1000 mg", "dose_quantity": 1, "dose_unit": "tablet", "instructions": "With dinner"},
    ]}).get_json()
    api.put(p, f"/prescription-items/{rx['items'][0]['id']}/schedule", {"times": [{"window_kind": "breakfast"}]})
    api.put(p, f"/prescription-items/{rx['items'][1]['id']}/schedule", {"times": [{"window_kind": "dinner"}]})
    assert api.post(p, f"/prescriptions/{rx['id']}/activate").status_code == 200
    set_now(BREAKFAST_0800)
    # No strength: both match by name, but only the 500 mg has a dose due -> matched.
    body = api.scan(p, strength=None).get_json()
    assert body["match_status"] == "matched" and body["medication"]["strength"] == "500 mg"
    # Before any window opens, both candidates are returned.
    early = (T0 - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    set_now(T0 - timedelta(hours=3))
    body = api.scan(p, strength=None, timestamp=early).get_json()
    assert body["match_status"] == "ambiguous" and len(body["candidates"]) == 2


def test_scan_rejects_other_user_and_future_timestamp(api):
    p = _setup(api)
    other = api.register("patient")
    r = api.post(p, "/scans", {"event_id": str(uuid.uuid4()), "user_id": other["id"], "drug_name": "Metformin",
                               "quantity": 1, "timestamp": "2026-10-12T11:00:00Z"})
    assert r.status_code == 403
    r = api.scan(p, timestamp="2026-10-12T12:00:00Z")  # one hour after frozen now
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "TIMESTAMP_IN_FUTURE"
    r = api.post(p, "/scans", {"event_id": str(uuid.uuid4()), "user_id": p["id"], "drug_name": "Metformin",
                               "quantity": 1, "timestamp": "2026-10-12T11:00:00"})  # no timezone
    assert r.status_code == 400


def test_confirm_from_scan_on_time_decrements_inventory(api, ctx):
    p = _setup(api)
    set_now(BREAKFAST_0800 + timedelta(minutes=10))
    scan = api.scan(p).get_json()
    set_now(BREAKFAST_0800 + timedelta(minutes=11))
    r = api.post(p, f"/doses/{scan['dose_event']['id']}/confirm", {"observation_event_id": scan["observation_event_id"]})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    dose = body["dose"]
    assert dose["status"] == "taken_on_time" and dose["confirmation_method"] == "scan"
    assert dose["taken_at"] == scan["observed_at"]
    assert dose["dose_mismatch"] is False
    assert body["inventory"] == {"tracked": True, "quantity_remaining": 59, "warning": None}
    txn = db.session.scalar(select(InventoryTransaction).where(InventoryTransaction.reason == "dose"))
    assert txn.delta == -1 and str(txn.dose_event_id) == dose["id"]
    outcome = db.session.scalar(select(DoseOutcome))
    assert outcome.status == "taken_on_time" and outcome.delay_minutes == 10
    # Pending dose_due / dose_followup reminders for this dose are cancelled
    statuses = set(db.session.scalars(select(Reminder.status).where(Reminder.dose_event_id == uuid.UUID(dose["id"]))))
    assert statuses == {"cancelled"}
    # Confirming twice is a conflict
    assert api.post(p, f"/doses/{dose['id']}/confirm", {}).status_code == 409


def test_on_time_boundary_and_late(api):
    p = _setup(api)
    doses = api.doses(p, p["id"])
    set_now(T0 + timedelta(hours=2))  # exactly on_time_end (09:00 local)
    assert api.post(p, f"/doses/{doses[0]['id']}/confirm", {}).get_json()["dose"]["status"] == "taken_on_time"
    set_now(T0 + timedelta(hours=13, minutes=1))  # 20:01 local, dinner on_time_end is 20:00
    assert api.post(p, f"/doses/{doses[1]['id']}/confirm", {}).get_json()["dose"]["status"] == "taken_late"


def test_confirm_before_window_is_rejected(api):
    p = _setup(api)
    dose = api.doses(p, p["id"])[1]  # dinner
    r = api.post(p, f"/doses/{dose['id']}/confirm", {})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "DOSE_NOT_DUE"


def test_dose_mismatch_flags_and_alerts_patient_and_caregiver(api, ctx):
    p = _setup(api)
    c = api.register("caregiver")
    api.link_caregiver(p, c)
    set_now(BREAKFAST_0800)
    scan = api.scan(p, quantity=2).get_json()
    assert scan["quantity_check"] == "mismatch"
    r = api.post(p, f"/doses/{scan['dose_event']['id']}/confirm", {"observation_event_id": scan["observation_event_id"]})
    dose = r.get_json()["dose"]
    assert dose["dose_mismatch"] is True and dose["quantity_taken"] == 2
    assert r.get_json()["inventory"]["quantity_remaining"] == 58
    alerts = db.session.scalars(select(Reminder).where(Reminder.kind == "dose_mismatch_alert")).all()
    assert {str(a.recipient_user_id) for a in alerts} == {p["id"], c["id"]}
    assert "2 tablets taken, 1 tablet prescribed" in alerts[0].body


def test_skip(api, ctx):
    p = _setup(api)
    dose = api.doses(p, p["id"])[0]
    r = api.post(p, f"/doses/{dose['id']}/skip")
    assert r.status_code == 200 and r.get_json()["dose"]["status"] == "skipped"
    assert db.session.scalar(select(DoseOutcome.status)) == "skipped"
    assert api.post(p, f"/doses/{dose['id']}/skip").status_code == 409
    assert db.session.scalar(select(func.count()).select_from(InventoryTransaction).where(InventoryTransaction.reason == "dose")) == 0


def test_insufficient_stock_still_records_dose(api, ctx):
    p = _setup(api, quantity_prescribed=1, dose_quantity=2)
    set_now(BREAKFAST_0800)
    dose = api.doses(p, p["id"])[0]
    r = api.post(p, f"/doses/{dose['id']}/confirm", {})
    assert r.status_code == 200
    assert r.get_json()["dose"]["status"] == "taken_on_time"
    assert r.get_json()["inventory"]["warning"] == "insufficient_recorded_stock"
