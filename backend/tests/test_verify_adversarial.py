"""Adversarial fail-closed tests for scan-vs-prescription verification (P0 safety).

Independent attack suite for ``app.hub.verify.scan_verification`` and the
``POST /hub/medications/<id>/doses`` eligibility check. These tests deliberately
try to reach ``due_now`` / ``not_due`` / ``already_taken`` (and, for due_now, a
``can_log=True``) without satisfying the full evidence contract:

    name state == "filled"
    AND normalized(casefold) name EXACTLY equals a tracked medication name
    AND strength readable, parseable, EXACTLY matching the same tracked item.

Everything weaker must fail closed (``uncertain`` / ``wrong_medication`` /
``strength_mismatch``, all with ``can_log=False``). Scans are read-only and must
never record a dose. Local fixtures only — no imports from ``test_hub.py``.
"""

import io
from datetime import timedelta
from types import SimpleNamespace

import pytest
from conftest import T0, set_now
from sqlalchemy import select

from app.extensions import db
from app.hub import labels
from app.hub import verify as hub_verify
from app.models import DoseEvent

HUB_EMAIL = "hub.patient@example.com"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
POSITIVE = ("due_now", "not_due", "already_taken")
FAIL_CLOSED = ("uncertain", "wrong_medication", "strength_mismatch")


def infer(
    name="Metformin",
    name_conf=0.95,
    strength=(500, "mg"),
    strength_conf=0.92,
    text="METFORMIN 500 mg TABLETS\nTake 1 tablet by mouth with meals.\nQTY: 60",
):
    """Crafted inference payload (mirrors the gateway contract shape)."""
    return {
        "status": "ok",
        "frame_quality": {"acceptable": True, "score": 0.9, "guidance": []},
        "label": {"detected": True, "confidence": 0.9, "text": text},
        "medication": {
            "name": {"value": name, "confidence": name_conf, "source": "ocr"},
            "strength": (
                {"value": strength[0], "unit": strength[1], "confidence": strength_conf, "source": "ocr"}
                if strength
                else {"value": None, "unit": None, "confidence": 0, "source": "none"}
            ),
            "form": {"value": "tablet", "confidence": 0.85, "source": "ocr"},
        },
        "instructions": {
            "raw_text": "Take 1 tablet by mouth with meals.",
            "parsed": [{"kind": "frequency", "text": "with meals"}],
            "dose": {"quantity": 1, "unit": "tablet", "confidence": 0.9, "source": "ocr"},
        },
    }


class FakeInference:
    """Queue-backed stand-in for the hub's inference HTTP call."""

    def __init__(self, monkeypatch):
        self.queue = []
        monkeypatch.setattr(labels.http, "post", self._post)

    def _post(self, url, files=None, data=None, headers=None, timeout=None):
        body = self.queue.pop(0)

        class R:
            status_code = 200

            def json(self_inner):
                return body

        return R()


@pytest.fixture
def hub(api, client):
    """Hub client for one patient tracking Metformin 500 mg at breakfast/lunch/dinner."""
    p = api.register("patient", name="Adv Patient", email=HUB_EMAIL)
    api.active_metformin(p, times=("breakfast", "lunch", "dinner"))

    class Hub:
        patient = p

        def post(self, path, json=None, **kw):
            return client.post(f"/hub{path}", json=json, **kw)

        def photo(self, path):
            return client.post(
                f"/hub{path}",
                data={"photo": (io.BytesIO(JPEG), "label.jpg", "image/jpeg")},
                content_type="multipart/form-data",
            )

        def state(self):
            r = client.get("/hub/state")
            assert r.status_code == 200, r.get_json()
            return r.get_json()

        def med(self, name="Metformin"):
            return next(m for m in self.state()["medications"] if m["name"] == name)

    hub = Hub()
    hub.api = api
    return hub


def add_active_rx(api, patient, name, value, unit, times=("breakfast",), form="tablet"):
    """Draft -> schedule -> activate an extra prescription (local helper)."""
    r = api.post(
        patient,
        f"/patients/{patient['id']}/prescriptions",
        {
            "items": [
                {
                    "name": name,
                    "strength": {"value": value, "unit": unit},
                    "dosage_form": form,
                    "dose_quantity": 1,
                    "dose_unit": form,
                    "route": "oral",
                    "quantity_prescribed": 60,
                    "refills_authorized": 2,
                    "instructions": f"Take 1 {form} by mouth.",
                }
            ]
        },
    )
    assert r.status_code == 201, r.get_json()
    created = r.get_json()
    item_id = created["items"][0]["id"]
    rx_id = created["id"]
    r = api.put(patient, f"/prescription-items/{item_id}/schedule", {"times": [{"window_kind": k} for k in times]})
    assert r.status_code == 200, r.get_json()
    r = api.post(patient, f"/prescriptions/{rx_id}/activate")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def scan_with(hub, monkeypatch, body):
    """Create one hub scan whose inference result is ``body``; return its JSON."""
    fake = FakeInference(monkeypatch)
    fake.queue = [body]
    r = hub.photo("/scans")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


# ---------------------------------------------------------------------------
# Required adversarial cases 1-14
# ---------------------------------------------------------------------------


def test_01_missing_name_is_uncertain_and_cannot_log(hub):
    """Case 1: no readable name -> uncertain, can_log False."""
    set_now(T0 + timedelta(hours=1))
    scan = hub.post("/scans", {"manual": True}).get_json()
    v = scan["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False


def test_02_unsure_name_is_uncertain_and_cannot_log(hub, monkeypatch):
    """Case 2: name read at 0.6 confidence (state unsure) is a lead, not identity."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    v = scan_with(hub, monkeypatch, infer(name="Metformin", name_conf=0.6))["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False


def test_03_missing_strength_is_uncertain_and_cannot_log(hub, monkeypatch):
    """Case 3: exact name but no readable strength -> uncertain, can_log False."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    v = scan_with(hub, monkeypatch, infer(strength=None))["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False
    assert "strength" in v["message"].lower()


def test_04_unsure_strength_is_uncertain_and_cannot_log(hub, monkeypatch):
    """Case 4: strength read at 0.6 (state unsure) cannot be checked -> uncertain."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    v = scan_with(hub, monkeypatch, infer(strength_conf=0.6))["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False


def test_05_exact_name_and_strength_is_positive(hub, monkeypatch):
    """Case 5: filled exact name + filled exact strength is the only positive path."""
    set_now(T0 + timedelta(hours=1, minutes=5))  # breakfast window open
    v = scan_with(hub, monkeypatch, infer())["verification"]
    assert v["status"] == "due_now" and v["can_log"] is True
    assert v["medication"]["name"] == "Metformin"
    assert v["medication"]["strength"] == "500 mg"
    assert v["matched"] == {"name": "exact", "strength": "exact"}


def test_06_fuzzy_only_name_is_candidate_not_proof(hub, monkeypatch):
    """Case 6: a near-spelling (fuzzy >= 88) must never be treated as identity."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    v = scan_with(hub, monkeypatch, infer(name="Metformn", name_conf=0.95))["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False


def test_07_wrong_strength_with_exact_name_is_mismatch(hub, monkeypatch):
    """Case 7: exact name but a different strength -> strength_mismatch, can_log False."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    v = scan_with(hub, monkeypatch, infer(strength=(850, "mg")))["verification"]
    assert v["status"] == "strength_mismatch" and v["can_log"] is False
    assert "850 mg" in v["message"]


def test_08_same_name_two_strengths_picks_the_scanned_one(hub, monkeypatch):
    """Case 8: with 500 and 1000 tracked, scanning 1000 selects the 1000 prescription."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    add_active_rx(hub.api, hub.patient, "Metformin", 1000, "mg")
    meds = hub.state()["medications"]
    thousand = next(m for m in meds if m["name"] == "Metformin" and m["strength"] == "1000 mg")
    v = scan_with(hub, monkeypatch, infer(strength=(1000, "mg")))["verification"]
    assert v["status"] in POSITIVE, v
    assert v["medication"]["strength"] == "1000 mg"
    assert v["medication"]["id"] == thousand["id"]


def test_09_two_strengths_none_match_is_mismatch_never_arbitrary(hub, monkeypatch):
    """Case 9: with 500 and 1000 tracked, scanning 850 matches neither -> strength_mismatch."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    add_active_rx(hub.api, hub.patient, "Metformin", 1000, "mg")
    v = scan_with(hub, monkeypatch, infer(strength=(850, "mg")))["verification"]
    assert v["status"] == "strength_mismatch" and v["can_log"] is False
    assert "850 mg" in v["message"]
    # never silently picks one of the tracked strengths as the match
    assert v.get("medication") is None


def test_10_ambiguous_same_strength_is_uncertain(ctx, monkeypatch):
    """Case 10: two tracked items with identical name+strength -> uncertain, no pick.

    The DB may prevent two identical active rows, so this drives the unit directly
    with two stubbed tracked items.
    """
    stubs = [
        (SimpleNamespace(id=1), SimpleNamespace(medication=SimpleNamespace(name="Metformin", strength="500 mg"))),
        (SimpleNamespace(id=2), SimpleNamespace(medication=SimpleNamespace(name="Metformin", strength="500 mg"))),
    ]
    monkeypatch.setattr(hub_verify.hub_state, "tracked", lambda patient: stubs)
    scan = SimpleNamespace(
        fields={
            "name": {"value": "Metformin", "state": "filled"},
            "strength": {"value": "500 mg", "state": "filled"},
        }
    )
    result = hub_verify.scan_verification(SimpleNamespace(id=1, timezone="America/New_York"), scan)
    assert result["status"] == "uncertain" and result["can_log"] is False


def test_11_already_taken_blocks_repeat_log(hub, monkeypatch):
    """Case 11: all doses logged -> already_taken; another log must 409 (fresh check)."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    med = hub.med("Metformin")
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200
    set_now(T0 + timedelta(hours=5, minutes=35))  # 12:35 lunch window
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200
    set_now(T0 + timedelta(hours=12, minutes=5))  # 19:05 dinner window
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200

    set_now(T0 + timedelta(hours=12, minutes=20))
    v = scan_with(hub, monkeypatch, infer())["verification"]
    assert v["status"] == "already_taken" and v["can_log"] is False
    repeat = hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"})
    assert repeat.status_code == 409, repeat.get_json()


def test_12_recent_earlier_dose_does_not_hide_later_dose(hub, monkeypatch):
    """Case 12: a dose taken 5 min ago (inside the old 6 h window) must not hide the 12:30 dose."""
    set_now(T0 + timedelta(hours=1, minutes=5))  # 08:05 breakfast window
    med = hub.med("Metformin")
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200
    set_now(T0 + timedelta(hours=1, minutes=10))  # 08:10 — inside RECENT_TAKEN_HOURS
    v = scan_with(hub, monkeypatch, infer())["verification"]
    assert v["status"] == "not_due" and v["can_log"] is False
    assert v["due_local"] == "12:30"


def test_13_scans_never_record_a_dose(hub, monkeypatch, ctx):
    """Case 13: any scan (including due_now) must leave dose rows and statuses untouched."""
    set_now(T0 + timedelta(hours=1, minutes=5))

    def dose_state():
        rows = db.session.scalars(
            select(DoseEvent).where(DoseEvent.patient_id == hub.patient["id"])
        ).all()
        return sorted((str(e.id), e.status) for e in rows)

    before = dose_state()
    assert scan_with(hub, monkeypatch, infer())["verification"]["status"] == "due_now"
    assert scan_with(hub, monkeypatch, infer(name="Losartan", strength=(25, "mg")))["verification"]["status"] == "wrong_medication"
    assert scan_with(hub, monkeypatch, infer(name="Metformn"))["verification"]["status"] == "uncertain"
    assert dose_state() == before


def test_14_stale_due_now_rescan_after_confirm(hub, monkeypatch):
    """Case 14: after confirming a scanned due_now dose, a rescan is not due_now and relogging 409s."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    med = hub.med("Metformin")
    v1 = scan_with(hub, monkeypatch, infer())["verification"]
    assert v1["status"] == "due_now" and v1["can_log"] is True and v1["dose_event_id"]

    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 200

    v2 = scan_with(hub, monkeypatch, infer())["verification"]
    assert v2["status"] != "due_now" and v2["can_log"] is False
    assert hub.post(f"/medications/{med['id']}/doses", {"method": "dashboard"}).status_code == 409


# ---------------------------------------------------------------------------
# Extra adversarial edges (fail-closed)
# ---------------------------------------------------------------------------


def test_15_unparseable_strength_fails_closed(hub, monkeypatch):
    """Filled but unparseable strength (e.g. 'unknown mg') must be uncertain, per the contract.

    FINDING (2026-10-12, tip bdcdc07/1466cf6): the engine returns ``strength_mismatch``
    instead of ``uncertain`` for unparseable-but-filled strength text. Both are
    fail-closed (can_log False), so this is a status-classification gap, not a safety
    hole. Test intentionally stays strict; see EVAL/report for the finding.
    """
    set_now(T0 + timedelta(hours=1, minutes=5))
    v = scan_with(hub, monkeypatch, infer(strength=("unknown", "mg")))["verification"]
    assert v["status"] == "uncertain" and v["can_log"] is False


def test_16_empty_strength_with_filled_state_fails_closed(ctx):
    """A filled state with an empty strength value must not slip past the gate."""
    scan = SimpleNamespace(
        fields={
            "name": {"value": "Metformin", "state": "filled"},
            "strength": {"value": "", "state": "filled"},
        }
    )
    result = hub_verify.scan_verification(SimpleNamespace(id=1, timezone="America/New_York"), scan)
    assert result["status"] == "uncertain" and result["can_log"] is False


def test_17_salt_form_name_is_not_an_exact_match(hub, monkeypatch):
    """'Metformin HCl' is not the tracked exact name; it must never reach a positive status."""
    set_now(T0 + timedelta(hours=1, minutes=5))
    v = scan_with(hub, monkeypatch, infer(name="Metformin HCl"))["verification"]
    assert v["status"] in FAIL_CLOSED and v["can_log"] is False


def test_18_can_log_true_only_for_due_now(hub, monkeypatch):
    """Sweep the positive statuses: can_log may be True only on due_now."""
    set_now(T0 + timedelta(hours=1, minutes=5))  # breakfast open
    assert scan_with(hub, monkeypatch, infer())["verification"]["can_log"] is True
    set_now(T0 - timedelta(hours=2))  # before any window
    assert scan_with(hub, monkeypatch, infer())["verification"]["can_log"] is False
