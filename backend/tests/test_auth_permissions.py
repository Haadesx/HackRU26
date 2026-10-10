import uuid


def test_register_seeds_five_default_windows(api):
    p = api.register("patient")
    r = api.get(p, f"/patients/{p['id']}/dose-windows")
    windows = {w["kind"]: w for w in r.get_json()["dose_windows"]}
    assert set(windows) == {"breakfast", "lunch", "dinner", "bedtime", "generic"}
    assert windows["breakfast"]["target_time"] == "08:00"
    assert windows["lunch"]["target_time"] == "12:30"
    assert windows["dinner"]["target_time"] == "19:00"
    assert windows["bedtime"]["target_time"] == "21:30"
    assert windows["generic"]["target_time"] is None
    assert (windows["lunch"]["on_time_before_min"], windows["lunch"]["on_time_after_min"], windows["lunch"]["missed_after_min"]) == (30, 60, 120)
    assert (windows["generic"]["on_time_after_min"], windows["generic"]["missed_after_min"]) == (30, 120)


def test_duplicate_email_conflicts(api, client):
    api.register("patient", email="dup@example.com")
    r = client.post(
        "/api/v1/auth/register",
        json={"name": "X", "email": "DUP@example.com", "password": "another-password", "role": "patient"},
    )
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "EMAIL_TAKEN"


def test_login_refresh_and_me(api, client):
    p = api.register("patient", email="login@example.com")
    bad = client.post("/api/v1/auth/login", json={"email": "login@example.com", "password": "wrong-password"})
    assert bad.status_code == 401 and bad.get_json()["error"]["code"] == "INVALID_CREDENTIALS"
    ok = client.post("/api/v1/auth/login", json={"email": "LOGIN@example.com", "password": "correct-horse-battery"})
    assert ok.status_code == 200
    r = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {p['refresh']}"})
    assert r.status_code == 200 and r.get_json()["access_token"]
    # access token can't be used as a refresh token
    assert client.post("/api/v1/auth/refresh", headers=api.h(p)).status_code == 401
    me = api.get(p, "/me").get_json()
    assert me["user"]["email"] == "login@example.com" and me["caregivers"] == []


def test_missing_token_and_validation_envelope(api, client):
    r = client.get("/api/v1/me")
    assert r.status_code == 401 and r.get_json()["error"]["code"] == "UNAUTHORIZED"
    r = client.post("/api/v1/auth/register", json={"email": "not-an-email", "role": "nurse"})
    assert r.status_code == 400
    body = r.get_json()["error"]
    assert body["code"] == "VALIDATION_ERROR" and "json" in body["details"]


def test_patch_me_validates_phone_and_timezone(api):
    p = api.register("patient")
    assert api.patch(p, "/me", {"phone": "555-1234"}).status_code == 400
    assert api.patch(p, "/me", {"timezone": "Mars/Olympus"}).status_code == 400
    r = api.patch(p, "/me", {"phone": "+15555550123", "sms_enabled": False})
    assert r.status_code == 200 and r.get_json()["user"]["phone"] == "+15555550123"


def test_caregiver_invite_accept_and_read_only_access(api):
    p = api.register("patient")
    c = api.register("caregiver")
    api.active_metformin(p)
    link = api.link_caregiver(p, c)
    assert link["status"] == "active"

    # Reads are allowed
    for path in ("/doses", "/inventory", "/prescriptions", "/dose-windows", "/refills", "/adherence", "/caregivers"):
        assert api.get(c, f"/patients/{p['id']}{path}").status_code == 200, path

    dose_id = api.doses(c, p["id"])[0]["id"]
    rx_id = api.get(c, f"/patients/{p['id']}/prescriptions").get_json()["prescriptions"][0]["id"]
    med_id = api.get(c, f"/patients/{p['id']}/inventory").get_json()["inventory"][0]["medication"]["id"]
    window_id = api.get(c, f"/patients/{p['id']}/dose-windows").get_json()["dose_windows"][0]["id"]

    # Every write is rejected for the caregiver
    writes = [
        ("post", f"/doses/{dose_id}/confirm", {}),
        ("post", f"/doses/{dose_id}/skip", {}),
        ("post", f"/patients/{p['id']}/prescriptions", {"items": [{"name": "Aspirin"}]}),
        ("post", f"/prescriptions/{rx_id}/revise", {}),
        ("put", f"/patients/{p['id']}/inventory/{med_id}", {"quantity_remaining": 5}),
        ("put", f"/dose-windows/{window_id}", {"on_time_after_min": 45}),
        ("post", f"/patients/{p['id']}/dose-windows", {"name": "Snack"}),
        ("post", f"/patients/{p['id']}/caregivers/invite", {"email": c["email"]}),
    ]
    for method, path, body in writes:
        r = getattr(api, method)(c, path, body)
        assert r.status_code == 403, (path, r.get_json())

    # Scans: caregiver is not a patient
    r = api.post(c, "/scans", {
        "event_id": str(uuid.uuid4()), "user_id": c["id"], "drug_name": "Metformin",
        "quantity": 1, "timestamp": "2026-10-12T11:00:00Z",
    })
    assert r.status_code == 403


def test_unlinked_users_cannot_read(api):
    p = api.register("patient")
    stranger = api.register("caregiver")
    other_patient = api.register("patient")
    assert api.get(stranger, f"/patients/{p['id']}/doses").status_code == 403
    assert api.get(other_patient, f"/patients/{p['id']}/inventory").status_code == 403


def test_revoked_caregiver_loses_access(api):
    p = api.register("patient")
    c = api.register("caregiver")
    link = api.link_caregiver(p, c)
    assert api.get(c, f"/patients/{p['id']}/doses").status_code == 200
    r = api.patch(p, f"/caregiver-links/{link['id']}", {"status": "revoked"})
    assert r.status_code == 200
    assert api.get(c, f"/patients/{p['id']}/doses").status_code == 403


def test_invite_requires_caregiver_account_and_right_acceptor(api):
    p = api.register("patient")
    c = api.register("caregiver")
    other = api.register("caregiver")
    assert api.post(p, f"/patients/{p['id']}/caregivers/invite", {"email": "nobody@example.com"}).status_code == 404
    code = api.post(p, f"/patients/{p['id']}/caregivers/invite", {"email": c["email"]}).get_json()["invite_code"]
    assert len(code) == 6
    assert api.post(other, "/caregivers/accept", {"code": code}).status_code == 403
    assert api.post(c, "/caregivers/accept", {"code": code.lower()}).status_code == 200
