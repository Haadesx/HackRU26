from datetime import timedelta

from conftest import T0, set_now
from sqlalchemy import select

from app.extensions import db
from app.jobs import tasks
from app.models import Reminder


def _setup(api):
    p = api.register("patient")
    rx = api.active_metformin(p)
    return p, rx


def test_inventory_initialized_from_prescription_with_estimate(api):
    p, rx = _setup(api)
    assert rx["inventory_initialized_for"]
    inv = api.get(p, f"/patients/{p['id']}/inventory").get_json()["inventory"][0]
    assert inv["quantity_remaining"] == 60 and inv["quantity_unit"] == "tablet"
    assert inv["estimated_days_remaining"] == 30.0  # 2 tablets/day
    txns = api.get(p, f"/patients/{p['id']}/inventory/{inv['medication']['id']}/transactions").get_json()["transactions"]
    assert [(t["reason"], t["delta"]) for t in txns] == [("manual_adjustment", 60)]


def test_manual_correction_writes_difference(api):
    p, _ = _setup(api)
    med_id = api.get(p, f"/patients/{p['id']}/inventory").get_json()["inventory"][0]["medication"]["id"]
    r = api.put(p, f"/patients/{p['id']}/inventory/{med_id}", {"quantity_remaining": 45, "note": "counted pills"})
    assert r.status_code == 200 and r.get_json()["quantity_remaining"] == 45
    txns = api.get(p, f"/patients/{p['id']}/inventory/{med_id}/transactions").get_json()["transactions"]
    assert txns[0]["delta"] == -15 and txns[0]["note"] == "counted pills"
    assert api.put(p, f"/patients/{p['id']}/inventory/{med_id}", {"quantity_remaining": -1}).status_code == 400


def test_untracked_inventory_is_not_zero(api):
    p = api.register("patient")
    rx = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{
        "name": "Lisinopril", "strength": "10 mg", "dose_quantity": 1, "dose_unit": "tablet", "instructions": "Once daily"}]}).get_json()
    api.put(p, f"/prescription-items/{rx['items'][0]['id']}/schedule", {"times": [{"window_kind": "breakfast"}]})
    api.post(p, f"/prescriptions/{rx['id']}/activate")
    inv = api.get(p, f"/patients/{p['id']}/inventory").get_json()["inventory"][0]
    assert inv["quantity_remaining"] is None and inv["tracked"] is False
    set_now(T0 + timedelta(hours=1))
    dose = api.doses(p, p["id"])[0]
    body = api.post(p, f"/doses/{dose['id']}/confirm", {}).get_json()
    assert body["inventory"]["tracked"] is False


def test_refill_lifecycle_updates_stock_and_notifies(api, ctx):
    p, rx = _setup(api)
    c = api.register("caregiver")
    api.link_caregiver(p, c)
    item_id = rx["prescription"]["items"][0]["id"]
    r = api.post(p, f"/patients/{p['id']}/refills", {"prescription_item_id": item_id})
    assert r.status_code == 201 and r.get_json()["status"] == "requested"
    refill_id = r.get_json()["id"]
    assert api.post(c, f"/patients/{p['id']}/refills", {"prescription_item_id": item_id}).status_code == 403

    r = api.patch(p, f"/refills/{refill_id}", {"appointment_at": "2026-10-15T18:00:00Z", "pharmacy_or_provider": "Main St Pharmacy"})
    assert r.status_code == 200 and r.get_json()["status"] == "scheduled"
    assert r.get_json()["caregiver_notified_at"] is not None

    r = api.post(p, f"/refills/{refill_id}/fulfill", {"quantity_added": 60})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["refill"]["status"] == "fulfilled"
    assert r.get_json()["inventory"]["quantity_remaining"] == 120
    assert api.post(p, f"/refills/{refill_id}/cancel").status_code == 409

    updates = db.session.scalars(select(Reminder).where(Reminder.kind == "refill_update")).all()
    assert len(updates) == 4  # scheduled + fulfilled, each to patient and caregiver
    assert any("Main St Pharmacy" in u.body and "Oct 15 at 14:00" in u.body for u in updates)
    refills = api.get(c, f"/patients/{p['id']}/refills").get_json()["refills"]
    assert refills[0]["quantity_added"] == 60


def test_adherence_buckets_in_patient_local_days(api, ctx):
    p, _ = _setup(api)
    doses = api.doses(p, p["id"], **{"from": "2026-10-12T00:00:00Z", "to": "2026-10-14T00:00:00Z"})
    # Day 1 breakfast on time, dinner (19:00 local = 23:00Z) late; day 2 breakfast missed.
    set_now(T0 + timedelta(hours=1, minutes=15))
    api.post(p, f"/doses/{doses[0]['id']}/confirm", {})
    set_now(T0 + timedelta(hours=13, minutes=30))  # 20:30 local
    api.post(p, f"/doses/{doses[1]['id']}/confirm", {})
    later = T0 + timedelta(days=1, hours=3, minutes=5)
    set_now(later)
    tasks.mark_missed_doses(later)
    r = api.get(p, f"/patients/{p['id']}/adherence", query_string={"from": "2026-10-12T04:00:00Z", "to": "2026-10-14T04:00:00Z"})
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    buckets = body["buckets"]
    # Dinner at 23:00Z belongs to local Oct 12, not UTC Oct 13
    assert [b["bucket_start"] for b in buckets] == ["2026-10-12T04:00:00Z", "2026-10-13T04:00:00Z"]
    assert (buckets[0]["taken_on_time"], buckets[0]["taken_late"], buckets[0]["missed"]) == (1, 1, 0)
    assert buckets[0]["on_time_rate"] == 0.5
    assert buckets[1]["missed"] == 1 and buckets[1]["on_time_rate"] == 0.0
    assert body["summary"]["total"] == 3 and body["summary"]["taken_rate"] == 0.667
