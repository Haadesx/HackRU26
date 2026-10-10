from datetime import datetime, timedelta, timezone

from conftest import T0, set_now

from app.jobs import tasks


def test_activation_generates_48h_of_doses_with_snapshotted_windows(api):
    p = api.register("patient")
    result = api.active_metformin(p)  # breakfast 08:00 + dinner 19:00, America/New_York
    assert result["dose_events_created"] == 4
    doses = api.doses(p, p["id"], **{"from": "2026-10-12T00:00:00Z", "to": "2026-10-15T00:00:00Z"})
    assert [d["scheduled_at"] for d in doses] == [
        "2026-10-12T12:00:00Z",  # 08:00 EDT
        "2026-10-12T23:00:00Z",  # 19:00 EDT
        "2026-10-13T12:00:00Z",
        "2026-10-13T23:00:00Z",
    ]
    first = doses[0]
    assert first["window_name"] == "Breakfast"
    assert first["on_time_start"] == "2026-10-12T11:30:00Z"
    assert first["on_time_end"] == "2026-10-12T13:00:00Z"
    assert first["missed_after"] == "2026-10-12T14:00:00Z"
    # confirm_deadline = next dose of this schedule (19:00), capped at 24h
    assert first["confirm_deadline"] == "2026-10-12T23:00:00Z"
    assert doses[1]["confirm_deadline"] == "2026-10-13T12:00:00Z"
    assert all(d["status"] == "pending" and d["expected_quantity"] == 1 for d in doses)


def test_generation_is_idempotent_and_rolls_forward(api, ctx):
    p = api.register("patient")
    api.active_metformin(p)
    assert tasks.generate_dose_events(T0) == 0  # nothing new at the same instant
    set_now(T0 + timedelta(hours=12))
    # Horizon now ends Oct 14 23:00Z, so Oct 14 08:00 and 19:00 (inclusive) are added.
    assert tasks.generate_dose_events(T0 + timedelta(hours=12)) == 2
    assert len(api.doses(p, p["id"], **{"from": "2026-10-12T00:00:00Z", "to": "2026-10-16T00:00:00Z"})) == 6


def test_default_today_view_uses_patient_timezone(api):
    p = api.register("patient")
    api.active_metformin(p)
    today = api.doses(p, p["id"])
    assert [d["scheduled_at"] for d in today] == ["2026-10-12T12:00:00Z", "2026-10-12T23:00:00Z"]


def test_single_daily_dose_confirm_deadline_capped_at_24h(api):
    p = api.register("patient")
    api.active_metformin(p, times=("lunch",))
    first = api.doses(p, p["id"])[0]
    assert first["scheduled_at"] == "2026-10-12T16:30:00Z"
    assert first["confirm_deadline"] == "2026-10-13T16:30:00Z"


def test_dst_keeps_local_clock_time(api, ctx):
    p = api.register("patient")
    # Oct 31 2026 07:00 EDT; DST ends Nov 1 at 02:00
    start = datetime(2026, 10, 31, 11, 0, tzinfo=timezone.utc)
    set_now(start)
    api.active_metformin(p, times=("breakfast",))
    doses = api.doses(p, p["id"], **{"from": "2026-10-31T00:00:00Z", "to": "2026-11-03T00:00:00Z"})
    assert [d["scheduled_at"] for d in doses] == [
        "2026-10-31T12:00:00Z",  # 08:00 EDT (UTC-4)
        "2026-11-01T13:00:00Z",  # 08:00 EST (UTC-5)
    ]


def test_every_other_day_frequency(api):
    p = api.register("patient")
    rx = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{
        "name": "Vitamin D", "strength": "1000 IU", "dose_quantity": 1, "dose_unit": "capsule", "instructions": "Take 1 capsule."}]}).get_json()
    item_id = rx["items"][0]["id"]
    r = api.put(p, f"/prescription-items/{item_id}/schedule", {
        "frequency": "every_other_day", "start_date": "2026-10-12",
        "times": [{"window_kind": "generic", "local_time": "10:00"}]})
    assert r.status_code == 200, r.get_json()
    assert api.post(p, f"/prescriptions/{rx['id']}/activate").status_code == 200
    doses = api.doses(p, p["id"], **{"from": "2026-10-12T00:00:00Z", "to": "2026-10-16T00:00:00Z"})
    assert [d["scheduled_at"] for d in doses] == ["2026-10-12T14:00:00Z"]  # Oct 13 skipped, Oct 14 beyond 48h


def test_generic_window_requires_local_time(api):
    p = api.register("patient")
    rx = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{"name": "Aspirin", "strength": "81 mg"}]}).get_json()
    r = api.put(p, f"/prescription-items/{rx['items'][0]['id']}/schedule", {"times": [{"window_kind": "generic"}]})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "LOCAL_TIME_REQUIRED"


def test_activation_requires_complete_items(api):
    p = api.register("patient")
    rx = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{"name": "Aspirin", "strength": "81 mg"}]}).get_json()
    r = api.post(p, f"/prescriptions/{rx['id']}/activate")
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert err["code"] == "PRESCRIPTION_INCOMPLETE"
    problems = err["details"][rx["items"][0]["id"]]
    assert "instructions are required" in problems and any("schedule" in x for x in problems)


def test_window_edit_moves_future_doses_but_not_history(api, ctx):
    p = api.register("patient")
    api.active_metformin(p)
    windows = {w["kind"]: w for w in api.get(p, f"/patients/{p['id']}/dose-windows").get_json()["dose_windows"]}
    # Take the 08:00 dose, then move breakfast to 09:00 with a tighter window.
    set_now(T0 + timedelta(hours=1, minutes=10))  # 08:10 local
    first = api.doses(p, p["id"])[0]
    assert api.post(p, f"/doses/{first['id']}/confirm", {}).status_code == 200
    r = api.put(p, f"/dose-windows/{windows['breakfast']['id']}", {"target_time": "09:00", "on_time_after_min": 30})
    assert r.status_code == 200, r.get_json()
    doses = api.doses(p, p["id"], **{"from": "2026-10-12T00:00:00Z", "to": "2026-10-14T00:00:00Z"})
    by_time = {d["scheduled_at"]: d for d in doses}
    assert by_time["2026-10-12T12:00:00Z"]["status"] == "taken_on_time"  # history kept
    assert by_time["2026-10-12T12:00:00Z"]["on_time_end"] == "2026-10-12T13:00:00Z"  # old snapshot
    assert "2026-10-13T12:00:00Z" not in by_time  # tomorrow's 08:00 removed
    assert by_time["2026-10-13T13:00:00Z"]["on_time_end"] == "2026-10-13T13:30:00Z"  # new 09:00 dose, new window


def test_revise_and_activate_supersedes_without_duplicates(api, ctx):
    p = api.register("patient")
    first = api.active_metformin(p)
    rx_id = first["prescription"]["id"]
    set_now(T0 + timedelta(hours=1, minutes=5))
    dose = api.doses(p, p["id"])[0]
    api.post(p, f"/doses/{dose['id']}/confirm", {})
    draft = api.post(p, f"/prescriptions/{rx_id}/revise").get_json()
    assert draft["status"] == "draft" and draft["version"] == 2
    assert draft["items"][0]["schedule"]["times"][0]["window_name"] == "Breakfast"
    r = api.post(p, f"/prescriptions/{draft['id']}/activate")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["superseded_prescription_id"] == rx_id
    doses = api.doses(p, p["id"], **{"from": "2026-10-12T00:00:00Z", "to": "2026-10-14T00:00:00Z"})
    times = [d["scheduled_at"] for d in doses]
    assert len(times) == len(set(times)) == 4  # taken 08:00 dose kept, not regenerated
    assert doses[0]["status"] == "taken_on_time"
    statuses = {x["version"]: x["status"] for x in api.get(p, f"/patients/{p['id']}/prescriptions").get_json()["prescriptions"]}
    assert statuses == {1: "superseded", 2: "active"}
