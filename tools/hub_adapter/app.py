#!/usr/bin/env python3
"""MedCheck hub adapter — serves the web UI's hub contract from REAL inference.

This is the integration seam between:
  • the web UI (Sinchana)  — expects /health, /state, /scans, /scans/{id}/photos, …
  • the inference gateway (this repo) — POST /v1/scan and /v1/scan/multi on :8300
  • the backend (Urvi) — not required for this demo; state is an in-memory/file
    demo store seeded from frontend/docs/fixtures/state.json. When the real backend
    implements the hub contract it replaces this adapter; the inference mapping
    below is the reference for it.

Run:  .venv-full/bin/uvicorn tools.hub_adapter.app:app --host 127.0.0.1 --port 8500
UI:   cd frontend && VITE_API_URL=http://127.0.0.1:8500 npm run dev
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "frontend" / "docs" / "fixtures" / "state.json"
INFERENCE = os.environ.get("MEDCHECK_API", "http://127.0.0.1:8300").rstrip("/")
STATE_FILE = Path(os.environ.get("HUB_STATE_FILE", str(Path.home() / ".medcheck" / "hub_state.json")))
SCAN_DIR = Path(os.environ.get("HUB_SCANS_DIR", str(Path.home() / ".medcheck" / "hub_scans")))
CORS = os.environ.get("HUB_CORS_ORIGINS", "*")

app = FastAPI(title="MedCheck hub adapter", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS.split(",")] if CORS else [],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

FIELDS = ("name", "strength", "dose_amount", "schedule_times", "quantity_start",
          "refills_remaining", "pharmacy_name", "pharmacy_phone", "prescriber")
REQUIRED = ("name", "strength", "dose_amount", "schedule_times", "quantity_start")

# ---------------------------------------------------------------- state store

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _seed() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def _load() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:  # noqa: BLE001
            pass
    state = _seed()
    _save(state)
    return state


def _save(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


STATE: Dict[str, Any] = _load()
SEED: Dict[str, Any] = _seed()
SCAN_DIR.mkdir(parents=True, exist_ok=True)


def _next_id(items: List[Dict[str, Any]]) -> int:
    return max((int(i.get("id", 0)) for i in items), default=0) + 1


# ------------------------------------------------------- inference → 9 fields

def _fmt_num(value: Any) -> str:
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(f)) if f.is_integer() else str(f)


def _state_for(value: str, confidence: float) -> str:
    if not value:
        return "missing"
    if confidence >= 0.85:
        return "filled"
    if confidence >= 0.5:
        return "unsure"
    return "missing"


def _field(value: Any, confidence: float) -> Dict[str, str]:
    text = "" if value is None else str(value)
    st = _state_for(text, float(confidence or 0.0))
    return {"value": text if st != "missing" else "", "state": st}


def _candidates_from_state() -> List[Dict[str, Any]]:
    out = []
    for med in STATE.get("medications", []):
        item: Dict[str, Any] = {"name": med.get("name")}
        strength = med.get("strength") or ""
        parts = str(strength).split()
        if len(parts) == 2:
            try:
                item["strength"] = {"value": float(parts[0]), "unit": parts[1]}
            except ValueError:
                pass
        out.append(item)
    return out


def scan_to_fields(scan: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    med = scan.get("medication", {}) or {}
    name = med.get("name") or {}
    strength = med.get("strength") or {}
    dose = (scan.get("instructions") or {}).get("dose") or {}
    meta = scan.get("label_meta") or {}

    def meta_field(key: str) -> Dict[str, str]:
        f = meta.get(key) or {}
        return _field(f.get("value"), f.get("confidence", 0.0))

    strength_text = ""
    if strength.get("value") is not None:
        strength_text = f"{_fmt_num(strength['value'])} {strength.get('unit') or ''}".strip()
    return {
        "name": _field(name.get("value"), name.get("confidence", 0.0)),
        "strength": _field(strength_text, strength.get("confidence", 0.0)),
        "dose_amount": _field(_fmt_num(dose.get("quantity")), dose.get("confidence", 0.0)),
        "schedule_times": meta_field("schedule_times"),
        "quantity_start": meta_field("quantity_start"),
        "refills_remaining": meta_field("refills_remaining"),
        "pharmacy_name": meta_field("pharmacy_name"),
        "pharmacy_phone": meta_field("pharmacy_phone"),
        "prescriber": meta_field("prescriber"),
    }


def _sniff(data: bytes) -> tuple[str, str]:
    """(extension, content_type) from magic bytes — never trust the upload name."""
    if data.startswith(b"\x89PNG"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if len(data) > 12 and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return "jpg", "image/jpeg"


def _ctype_for(path: Path) -> str:
    return {"png": "image/png", "webp": "image/webp"}.get(path.suffix.lstrip(".").lower(), "image/jpeg")


def run_inference(photos: List[Path]) -> Dict[str, Any]:
    hints = {"known_candidates": _candidates_from_state()}
    try:
        with httpx.Client(timeout=120) as client:
            if len(photos) == 1:
                with photos[0].open("rb") as fh:
                    resp = client.post(f"{INFERENCE}/v1/scan",
                                       files={"image": (photos[0].name, fh, _ctype_for(photos[0]))},
                                       data={"mode": "real", "client": "backend",
                                             "hints": json.dumps(hints)})
            else:
                files = [("images", (p.name, p.open("rb"), _ctype_for(p))) for p in photos]
                try:
                    resp = client.post(f"{INFERENCE}/v1/scan/multi", files=files,
                                       data={"mode": "real", "client": "backend",
                                             "hints": json.dumps(hints)})
                finally:
                    for _, (_, fh, _) in files:
                        fh.close()
        resp.raise_for_status()
        body = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"inference unavailable: {exc}") from exc
    if body.get("status") == "error":
        detail = (body.get("error") or {}).get("message") or "inference could not read that image"
        raise HTTPException(status_code=422, detail=detail)
    return body


def merge_fields(old: Dict[str, Dict[str, str]], new: Dict[str, Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    """Keep the better state per field: filled > unsure > missing; never downgrade."""
    rank = {"filled": 2, "unsure": 1, "missing": 0}
    merged = {}
    for key in FIELDS:
        a, b = old.get(key, {"value": "", "state": "missing"}), new.get(key, {"value": "", "state": "missing"})
        best = a if rank[a["state"]] >= rank[b["state"]] else b
        merged[key] = {"value": best["value"], "state": best["state"]}
    return merged


def _new_scan(scan_id: int, manual: bool = False) -> Dict[str, Any]:
    return {
        "id": scan_id,
        "status": "reading",
        "photos": 0,
        "manual": manual,
        "created_at": _now(),
        "fields": {k: {"value": "", "state": "missing"} for k in FIELDS},
        "history": [{"step": "Scanned" if not manual else "Entered by hand", "at": _now(),
                     "detail": "Starting a new scan."}],
    }


def _scan_or_404(scan_id: int) -> Dict[str, Any]:
    for s in STATE.get("scans", []):
        if int(s["id"]) == int(scan_id):
            return s
    raise HTTPException(status_code=404, detail=f"scan {scan_id} not found")


def _read_photo(scan: Dict[str, Any], photo: UploadFile) -> Dict[str, Any]:
    data = photo.file.read()
    ext, _ = _sniff(data)
    path = SCAN_DIR / f"{scan['id']}_{scan['photos'] + 1}.{ext}"
    path.write_bytes(data)
    scan["photos"] += 1
    photos = sorted(p for p in SCAN_DIR.glob(f"{scan['id']}_*") if p.is_file())
    result = run_inference(photos)
    fields = scan_to_fields(result)
    scan["fields"] = merge_fields(scan["fields"], fields)
    filled = sum(1 for f in scan["fields"].values() if f["state"] != "missing")
    scan["history"].append({"step": "Scanned" if scan["photos"] == 1 else f"Photo {scan['photos']}",
                            "at": _now(), "detail": f"Read {filled} of 9 details."})
    missing = [k for k in REQUIRED if scan["fields"][k]["state"] == "missing"]
    scan["status"] = "needs_caregiver" if missing else "asking_patient"
    if scan["status"] == "needs_caregiver":
        scan["history"].append({"step": "Sent to you", "at": _now(),
                                "detail": f"Missing: {', '.join(missing)}. Waiting for you now."})
    _save(STATE)
    return scan


# ------------------------------------------------------------------- endpoints

@app.get("/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


@app.get("/state")
def get_state() -> Dict[str, Any]:
    state = copy.deepcopy(STATE)
    state["hub"] = {"connected": True}
    return state


@app.post("/scans")
async def start_scan(request: Request) -> Dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    scan = _new_scan(_next_id(STATE.get("scans", [])), manual=(not content_type.startswith("multipart")))
    STATE.setdefault("scans", []).append(scan)
    if content_type.startswith("multipart"):
        form = await request.form()
        photo = form.get("photo")
        if photo is not None and hasattr(photo, "file"):
            scan = _read_photo(scan, photo)
    _save(STATE)
    return scan


@app.post("/scans/{scan_id}/photos")
async def add_photo(scan_id: int, photo: UploadFile = File(...)) -> Dict[str, Any]:
    scan = _scan_or_404(scan_id)
    return _read_photo(scan, photo)


@app.get("/scans/{scan_id}")
def get_scan(scan_id: int) -> Dict[str, Any]:
    return _scan_or_404(scan_id)


@app.delete("/scans/{scan_id}")
def discard_scan(scan_id: int) -> Dict[str, Any]:
    scan = _scan_or_404(scan_id)
    STATE["scans"] = [s for s in STATE["scans"] if s is not scan]
    for p in SCAN_DIR.glob(f"{scan_id}_*"):
        p.unlink(missing_ok=True)
    _save(STATE)
    return get_state()


@app.post("/scans/{scan_id}/complete")
async def complete_scan(scan_id: int, values: Dict[str, Any]) -> Dict[str, Any]:
    scan = _scan_or_404(scan_id)
    missing = [k for k in REQUIRED if not str(values.get(k, "")).strip()]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required fields: {', '.join(missing)}")
    schedule = [t.strip() for t in str(values.get("schedule_times", "")).split(",") if t.strip()]
    qty = int(float(values.get("quantity_start") or 0))
    refills = values.get("refills_remaining")
    med = {
        "id": _next_id(STATE.get("medications", [])),
        "name": str(values["name"]).strip(),
        "strength": str(values["strength"]).strip(),
        "purpose": f"for {str(values.get('prescriber') or 'your prescription').strip()}".strip(),
        "dose_amount": float(values["dose_amount"]) if _is_float(values["dose_amount"]) else values["dose_amount"],
        "doses_per_day": max(1, len(schedule)),
        "schedule_times": schedule,
        "quantity_start": qty,
        "pills_left": qty,
        "refills_remaining": int(float(refills)) if str(refills or "").strip() else None,
        "fill_date": datetime.now(timezone.utc).date().isoformat(),
        "instructions": f"Take {values['dose_amount']} at {', '.join(schedule)}",
        "prescriber": values.get("prescriber") or None,
        "pharmacy_name": values.get("pharmacy_name") or None,
        "pharmacy_phone": values.get("pharmacy_phone") or None,
    }
    if med["dose_amount"] == int(med["dose_amount"]) if isinstance(med["dose_amount"], float) else False:
        med["dose_amount"] = int(med["dose_amount"])
    STATE.setdefault("medications", []).append(med)
    scan["status"] = "complete"
    scan["history"].append({"step": "Added", "at": _now(), "detail": f"Tracking {med['name']}."})
    _save(STATE)
    return {"medication": med}


def _is_float(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


@app.post("/medications/{med_id}/doses")
async def log_dose(med_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    med = _med_or_404(med_id)
    slot = body.get("slot") or (med["schedule_times"][0] if med.get("schedule_times") else "08:00")
    STATE.setdefault("doses", []).append({
        "id": _next_id(STATE.get("doses", [])),
        "medication_id": med_id, "slot": slot,
        "date": datetime.now(timezone.utc).date().isoformat(),
        "taken_at": _now(), "method": body.get("method", "dashboard"),
    })
    _save(STATE)
    return get_state()


@app.post("/medications/{med_id}/remind")
async def remind(med_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    _med_or_404(med_id)
    STATE.setdefault("reminders", []).append({
        "id": _next_id(STATE.get("reminders", [])), "medication_id": med_id,
        "slot": body.get("slot") or "08:00", "sent_at": _now(),
    })
    _save(STATE)
    return get_state()


@app.post("/medications/{med_id}/counts")
async def record_count(med_id: int, body: Dict[str, Any]) -> Dict[str, Any]:
    med = _med_or_404(med_id)
    med["pills_left"] = int(body.get("count", med.get("pills_left", 0)))
    _save(STATE)
    return get_state()


@app.post("/medications/{med_id}/refill")
async def refill(med_id: int) -> Dict[str, Any]:
    med = _med_or_404(med_id)
    med["pills_left"] = int(med.get("pills_left") or 0) + int(med.get("quantity_start") or 0)
    if med.get("refills_remaining") is not None:
        med["refills_remaining"] = max(0, int(med["refills_remaining"]) - 1)
    med["fill_date"] = datetime.now(timezone.utc).date().isoformat()
    _save(STATE)
    return get_state()


@app.patch("/medications/{med_id}")
async def patch_medication(med_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    med = _med_or_404(med_id)
    med.update({k: v for k, v in patch.items() if k in med})
    _save(STATE)
    return get_state()


@app.delete("/medications/{med_id}")
async def stop_tracking(med_id: int) -> Dict[str, Any]:
    STATE["medications"] = [m for m in STATE["medications"] if int(m["id"]) != int(med_id)]
    _save(STATE)
    return get_state()


def _med_or_404(med_id: int) -> Dict[str, Any]:
    for med in STATE.get("medications", []):
        if int(med["id"]) == int(med_id):
            return med
    raise HTTPException(status_code=404, detail=f"medication {med_id} not found")


@app.get("/adherence")
def adherence(month: Optional[str] = None) -> Dict[str, Any]:
    fixture = json.loads((ROOT / "frontend" / "docs" / "fixtures" / "adherence.json").read_text())
    return fixture


@app.put("/settings")
async def save_settings(body: Dict[str, Any]) -> Dict[str, Any]:
    STATE["settings"] = body
    _save(STATE)
    return get_state()


@app.get("/export")
def export_data() -> Response:
    payload = json.dumps(STATE, indent=2).encode()
    return Response(content=payload, media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=medcheck-export.json"})


@app.delete("/data")
def delete_all() -> Dict[str, Any]:
    settings = STATE.get("settings")
    fresh = _seed()
    fresh["settings"] = settings or fresh["settings"]
    STATE.clear()
    STATE.update(fresh)
    _save(STATE)
    return get_state()


@app.post("/demo/advance")
async def demo_advance(body: Dict[str, Any]) -> Dict[str, Any]:
    return get_state()


@app.post("/demo/reset")
def demo_reset() -> Dict[str, Any]:
    STATE.clear()
    STATE.update(copy.deepcopy(SEED))
    _save(STATE)
    return get_state()
