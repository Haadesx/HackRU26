import pytest

from app.services import openfda
from app.services.normalize import normalize_name, normalize_strength


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("500mg", "500 mg"),
        ("500 MG", "500 mg"),
        ({"value": 500, "unit": "mg"}, "500 mg"),
        ({"value": 0.5, "unit": "mg"}, "0.5 mg"),
        ("500.0 mg", "500 mg"),
        ("500 mg/1", "500 mg"),
        ("5 mg/mL", "5 mg/mL"),
        ("10 mg/5 mL", "10 mg/5 mL"),
        ("25 mcg", "25 mcg"),
        ("25 µg", "25 mcg"),
        ("1000 IU", "1000 IU"),
        ("", None),
        (None, None),
        ({"value": None, "unit": None}, None),
    ],
)
def test_normalize_strength(raw, expected):
    assert normalize_strength(raw) == expected


def test_normalize_name():
    assert normalize_name("  METFORMIN HCl. ") == "metformin hcl"


CANDIDATES = [
    {"openfda_id": "0001-1111", "brand_name": "Glucophage", "generic_name": "METFORMIN HYDROCHLORIDE",
     "dosage_form": "tablet", "strengths": ["500 mg", "850 mg"], "rxcui": "861007"},
    {"openfda_id": "0002-2222", "brand_name": "Metformin", "generic_name": "METFORMIN HYDROCHLORIDE",
     "dosage_form": "tablet", "strengths": ["1000 mg"], "rxcui": "861010"},
]


def test_best_match_uses_strength():
    assert openfda.best_match("Metformin", "1000 mg", CANDIDATES)["openfda_id"] == "0002-2222"
    assert openfda.best_match("Metformin", "500 mg", CANDIDATES)["openfda_id"] == "0001-1111"
    assert openfda.best_match("Metformin", "750 mg", CANDIDATES) is None
    assert openfda.best_match("Lisinopril", None, CANDIDATES) is None


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_create_draft_verifies_against_openfda(api, app, monkeypatch):
    import requests

    seen = {}

    def fake_get(url, params, timeout):
        seen["params"] = params
        return _Resp(200, {"results": [{
            "product_ndc": "0001-1111", "brand_name": "Glucophage", "generic_name": "METFORMIN HYDROCHLORIDE",
            "dosage_form": "TABLET, FILM COATED",
            "active_ingredients": [{"name": "METFORMIN HYDROCHLORIDE", "strength": "500 mg/1"}],
            "openfda": {"rxcui": ["861007"]},
        }]})

    monkeypatch.setattr(requests, "get", fake_get)
    app.config["OPENFDA_ENABLED"] = True
    try:
        p = api.register("patient")
        r = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{"name": "Metformin", "strength": "500mg"}]})
        item = r.get_json()["items"][0]
        assert item["verification"]["status"] == "verified"
        assert item["medication"]["verified"] is True and item["medication"]["rxcui"] == "861007"
        assert 'generic_name:"Metformin"' in seen["params"]["search"]
    finally:
        app.config["OPENFDA_ENABLED"] = False


def test_openfda_outage_is_a_warning_not_an_error(api, app, monkeypatch):
    import requests

    def boom(*a, **kw):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", boom)
    app.config["OPENFDA_ENABLED"] = True
    try:
        p = api.register("patient")
        rx = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{
            "name": "Metformin", "strength": "500 mg", "dose_quantity": 1, "dose_unit": "tablet", "instructions": "With food"}]}).get_json()
        assert rx["items"][0]["verification"]["status"] == "unavailable"
        api.put(p, f"/prescription-items/{rx['items'][0]['id']}/schedule", {"times": [{"window_kind": "lunch"}]})
        r = api.post(p, f"/prescriptions/{rx['id']}/activate")
        assert r.status_code == 200
        assert r.get_json()["warnings"][0]["code"] == "OPENFDA_UNAVAILABLE"
    finally:
        app.config["OPENFDA_ENABLED"] = False


def test_medications_dedupe(api):
    p = api.register("patient")
    a = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{"name": "Metformin", "strength": "500mg", "dosage_form": "Tablet"}]}).get_json()
    b = api.post(p, f"/patients/{p['id']}/prescriptions", {"items": [{"name": "metformin", "strength": "500 MG", "dosage_form": "tablet"}]}).get_json()
    assert a["items"][0]["medication"]["id"] == b["items"][0]["medication"]["id"]
    assert b["version"] == 2
