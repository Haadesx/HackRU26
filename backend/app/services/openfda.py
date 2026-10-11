"""OpenFDA drug lookup (NDC directory). Results are cached on the medications row.

Network failures and timeouts never raise: the medication stays unverified and
activation reports a warning (plan.md 5.3).
"""

import logging
import re

import requests
from flask import current_app
from rapidfuzz import fuzz

from app.models import Medication
from app.services.normalize import normalize_name, normalize_strength
from app.utils import http
from app.utils.time import utcnow

log = logging.getLogger(__name__)

NDC_URL = "https://api.fda.gov/drug/ndc.json"
NAME_MATCH_THRESHOLD = 85


def _query_term(name: str) -> str:
    # Keep characters that are safe inside a Lucene phrase.
    return re.sub(r"[^A-Za-z0-9 \-]", " ", name).strip()


def _candidate(result: dict) -> dict:
    ingredients = result.get("active_ingredients") or []
    openfda = result.get("openfda") or {}
    rxcuis = openfda.get("rxcui") or []
    return {
        "openfda_id": result.get("product_ndc"),
        "brand_name": result.get("brand_name"),
        "generic_name": result.get("generic_name"),
        "dosage_form": (result.get("dosage_form") or "").lower() or None,
        "strengths": [normalize_strength(i.get("strength")) for i in ingredients if i.get("strength")],
        "rxcui": rxcuis[0] if rxcuis else None,
    }


def search(name: str, limit: int = 10) -> dict:
    """Return {"available": bool, "candidates": [...]}. available=False on network errors or when disabled."""
    cfg = current_app.config
    term = _query_term(name)
    if not cfg.get("OPENFDA_ENABLED") or not term:
        return {"available": False, "candidates": []}
    params = {"search": f'generic_name:"{term}" brand_name:"{term}"', "limit": limit}
    if cfg.get("OPENFDA_API_KEY"):
        params["api_key"] = cfg["OPENFDA_API_KEY"]
    try:
        resp = http.get(NDC_URL, params=params, timeout=cfg.get("OPENFDA_TIMEOUT_S", 5))
    except requests.RequestException as exc:
        log.warning("OpenFDA request failed: %s", exc)
        return {"available": False, "candidates": []}
    if resp.status_code == 404:  # OpenFDA returns 404 for "no matches"
        return {"available": True, "candidates": []}
    if resp.status_code != 200:
        log.warning("OpenFDA returned HTTP %s", resp.status_code)
        return {"available": False, "candidates": []}
    try:
        results = resp.json().get("results") or []
    except ValueError:
        return {"available": False, "candidates": []}
    return {"available": True, "candidates": [_candidate(r) for r in results]}


def _name_score(name: str, cand: dict) -> float:
    target = normalize_name(name)
    scores = [
        fuzz.token_set_ratio(target, normalize_name(cand.get(field)))
        for field in ("generic_name", "brand_name")
        if cand.get(field)
    ]
    return max(scores, default=0)


def best_match(name: str, strength: str | None, candidates: list[dict]) -> dict | None:
    """First candidate whose name matches and, if a strength is known, whose strengths include it."""
    for cand in candidates:
        if _name_score(name, cand) < NAME_MATCH_THRESHOLD:
            continue
        if strength and strength not in cand["strengths"]:
            continue
        return cand
    return None


def verify_medication(med: Medication) -> dict:
    """Look up `med` and store the match. Returns {"status": verified|unverified|unavailable, "candidates"}."""
    if med.verified:
        return {"status": "verified", "candidates": []}
    result = search(med.name)
    if not result["available"]:
        return {"status": "unavailable", "candidates": []}
    match = best_match(med.name, med.strength, result["candidates"])
    if match is None:
        return {"status": "unverified", "candidates": result["candidates"][:5]}
    med.verified = True
    med.verified_at = utcnow()
    med.openfda_id = match["openfda_id"]
    med.rxcui = match["rxcui"]
    # dosage_form is part of the medication's identity key, so it is never rewritten from OpenFDA.
    return {"status": "verified", "candidates": [match]}
