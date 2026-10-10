#!/usr/bin/env python3
"""End-to-end: MedCheck inference scan → backend scan ingest (Urvi) → optional confirm.

Proves the documented client mapping:
    drug_name ← medication.name.value
    strength  ← medication.strength {value,unit}      (None when absent)
    quantity  ← instructions.dose.quantity (v1.1)     (fallback 1 only when absent)
    event_id  ← client UUID (idempotent), timestamp ← client UTC

Usage:
    # dry-run: scan inference and print the exact backend payload (no backend needed)
    .venv-full/bin/python scripts/e2e_scan_to_backend.py --dry-run

    # full flow (backend must be running; see docs/client-integration.md)
    .venv-full/bin/python scripts/e2e_scan_to_backend.py \
        --backend http://127.0.0.1:8000/api/v1 --email demo@example.com --password "$SEED_PASSWORD" --confirm

Exit codes: 0 ok · 1 failure · 2 bad usage/input.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def infer(scan_url: str, image: bytes, mode: str, hints: dict | None) -> dict:
    files = {"image": ("scan.png", image, "image/png")}
    data = {"mode": mode, "client": "backend"}
    if hints:
        data["hints"] = json.dumps(hints)
    with httpx.Client(timeout=90) as client:
        resp = client.post(scan_url, files=files, data=data)
    resp.raise_for_status()
    body = resp.json()
    if body.get("status") == "error":
        raise SystemExit(f"inference returned error: {body.get('error')}")
    return body


def to_backend_payload(scan: dict, user_id: str | None) -> dict:
    med = scan["medication"]
    name = (med.get("name") or {}).get("value")
    if not name:
        raise SystemExit("scan produced no medication name — nothing to send to the backend")
    strength = med.get("strength") or {}
    dose = (scan.get("instructions") or {}).get("dose") or {}
    quantity = dose.get("quantity")
    return {
        "event_id": str(uuid.uuid4()),
        "user_id": user_id,
        "drug_name": name,
        "strength": {"value": strength.get("value"), "unit": strength.get("unit")}
        if strength.get("value") is not None
        else None,
        "quantity": quantity if quantity is not None else 1,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def login(base: str, email: str, password: str) -> tuple[str, str]:
    with httpx.Client(timeout=30) as client:
        auth = client.post(f"{base}/auth/login", json={"email": email, "password": password})
        if auth.status_code != 200:
            raise SystemExit(f"login failed ({auth.status_code}): {auth.text[:300]}")
        token = auth.json().get("access_token")
        me = client.get(f"{base}/me", headers={"Authorization": f"Bearer {token}"})
        if me.status_code != 200:
            raise SystemExit(f"GET /me failed ({me.status_code}): {me.text[:300]}")
        user_id = (me.json().get("id") or (me.json().get("user") or {}).get("id"))
    if not token or not user_id:
        raise SystemExit("login/me did not return access_token + user id")
    return token, user_id


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(ROOT / "samples" / "label_metformin.png"))
    ap.add_argument("--inference", default="http://127.0.0.1:8300")
    ap.add_argument("--backend", default="http://127.0.0.1:8000/api/v1")
    ap.add_argument("--mode", default="real", choices=["real", "mock"])
    ap.add_argument("--email", default=None)
    ap.add_argument("--password", default=None)
    ap.add_argument("--hints", default=None, help="path to a JSON file with known_candidates")
    ap.add_argument("--confirm", action="store_true", help="also POST /doses/{id}/confirm")
    ap.add_argument("--dry-run", action="store_true", help="stop after printing the backend payload")
    args = ap.parse_args()

    image = Path(args.image).read_bytes()
    hints = json.loads(Path(args.hints).read_text()) if args.hints else None

    print(f"→ scanning {args.image} via {args.inference} (mode={args.mode})")
    scan = infer(f"{args.inference}/v1/scan", image, args.mode, hints)
    med = scan["medication"]
    print(f"  status={scan['status']} name={med['name']['value']!r} "
          f"strength={med.get('strength', {}).get('value')}{med.get('strength', {}).get('unit') or ''} "
          f"dose={scan['instructions'].get('dose')} vlm={scan['interpretation']['available']}")

    payload = to_backend_payload(scan, user_id="<from /me>")
    print("→ backend payload:")
    print(json.dumps(payload, indent=2))
    if args.dry_run:
        return 0

    if not (args.email and args.password):
        print("--email/--password required for a live backend run (or use --dry-run)", file=sys.stderr)
        return 2

    token, user_id = login(args.backend, args.email, args.password)
    payload["user_id"] = user_id
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=30) as client:
        resp = client.post(f"{args.backend}/scans", json=payload, headers=headers)
        print(f"→ POST /scans → {resp.status_code}")
        print(json.dumps(resp.json(), indent=2)[:1200])
        if resp.status_code != 200:
            return 1
        body = resp.json()
        dose_id = (body.get("dose_event") or {}).get("id")
        if args.confirm and dose_id:
            conf = client.post(
                f"{args.backend}/doses/{dose_id}/confirm",
                json={"observation_event_id": payload["event_id"]},
                headers=headers,
            )
            print(f"→ POST /doses/{dose_id}/confirm → {conf.status_code}")
            print(json.dumps(conf.json(), indent=2)[:800])
            return 0 if conf.status_code == 200 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
