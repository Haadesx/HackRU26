"""MedCheck hub adapter — backend mode.

Maps Urvi's backend API (`/api/v1`) onto the web UI's hub contract so Sinchana's
frontend runs on the REAL backend (timescale prescriptions/doses/inventory) with
REAL inference for scans.

Env:
    HUB_BACKEND_URL      default http://127.0.0.1:8000/api/v1
    HUB_BACKEND_EMAIL    default demo.patient@example.com (seeded)
    HUB_BACKEND_PASSWORD default medcheck-demo-password (seeded)

Every call re-logs-in once on 401. Failures raise BackendUnavailable so the
adapter can fall back to demo state instead of breaking the UI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx


class BackendUnavailable(RuntimeError):
    pass


class DoseNotDue(RuntimeError):
    pass


def _fmt_num(value: Any) -> Any:
    if value is None:
        return None
    f = float(value)
    return int(f) if f.is_integer() else f


class BackendStore:
    def __init__(self, base: str, email: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.email = email
        self.password = password
        self._token: Optional[str] = None
        self._user: Optional[Dict[str, Any]] = None
        self._windows: List[Dict[str, Any]] = []
        self._item_cache: Dict[str, Dict[str, Any]] = {}  # item_id -> {medication_id, ...}
        self._client = httpx.Client(timeout=30)

    # ------------------------------------------------------------------ http
    def _login(self) -> None:
        try:
            r = self._client.post(f"{self.base}/auth/login",
                                  json={"email": self.email, "password": self.password})
            r.raise_for_status()
            self._token = r.json()["access_token"]
        except Exception as exc:  # noqa: BLE001
            raise BackendUnavailable(f"login failed: {exc}") from exc

    def _request(self, method: str, path: str, *, retry: bool = True, **kwargs) -> Any:
        if self._token is None:
            self._login()
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            r = self._client.request(method, f"{self.base}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendUnavailable(str(exc)) from exc
        if r.status_code == 401 and retry:
            self._token = None
            self._login()
            return self._request(method, path, retry=False, **kwargs)
        if r.status_code >= 400:
            raise BackendUnavailable(f"{method} {path} -> {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else {}

    def patient(self) -> Dict[str, Any]:
        me = self._request("GET", "/me")
        self._user = me["user"]
        return self._user

    # ------------------------------------------------------------- mapping
    def _dose_windows(self) -> List[Dict[str, Any]]:
        if not self._windows:
            pid = self.patient()["id"]
            self._windows = self._request("GET", f"/patients/{pid}/dose-windows").get("dose_windows", [])
        return self._windows

    def _nearest_kind(self, local_time: str) -> str:
        def minutes(t: str) -> int:
            h, _, m = t.partition(":")
            return int(h) * 60 + int(m or 0)

        target = minutes(local_time)
        best = min(self._dose_windows(), key=lambda w: abs(minutes(w.get("target_time") or "08:00") - target),
                   default={"kind": "breakfast"})
        return str(best.get("kind") or "breakfast")

    def _active_items(self, pid: str) -> List[Dict[str, Any]]:
        data = self._request("GET", f"/patients/{pid}/prescriptions/active")
        if isinstance(data, list):
            rxs = data
        elif isinstance(data, dict) and data.get("items"):
            rxs = [data]
        else:
            rxs = data.get("prescriptions") or []
        items: List[Dict[str, Any]] = []
        for rx in rxs:
            for item in rx.get("items", []):
                item["_rx_id"] = rx.get("id")
                items.append(item)
        return items

    def _inventory_map(self, pid: str) -> Dict[str, Dict[str, Any]]:
        data = self._request("GET", f"/patients/{pid}/inventory")
        return {row["medication"]["id"]: row for row in data.get("inventory", [])}

    def _doses(self, pid: str, days_back: int = 7) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=days_back)).isoformat().replace("+00:00", "Z")
        end = (now + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        data = self._request("GET", f"/patients/{pid}/doses", params={"from": start, "to": end})
        return data.get("doses", [])

    def build_state(self, local: Dict[str, Any]) -> Dict[str, Any]:
        """Backend data → the UI's state shape. Local keeps scans/settings/reminders."""
        user = self.patient()
        pid = user["id"]
        items = self._active_items(pid)
        inventory = self._inventory_map(pid)
        doses = self._doses(pid)

        self._item_cache = {item["id"]: item for item in items}

        medications = []
        for item in items:
            med = item.get("medication") or {}
            times = [t.get("local_time") for t in (item.get("schedule") or {}).get("times", []) if t.get("local_time")]
            inv = inventory.get(med.get("id"), {})
            medications.append({
                "id": item["id"],
                "name": med.get("name"),
                "strength": med.get("strength"),
                "purpose": "",
                "dose_amount": item.get("dose_quantity", 1),
                "doses_per_day": max(1, len(times)),
                "schedule_times": times,
                "quantity_start": item.get("quantity_prescribed"),
                "pills_left": inv.get("quantity_remaining"),
                "refills_remaining": item.get("refills_authorized"),
                "fill_date": (item.get("schedule") or {}).get("start_date"),
                "instructions": item.get("instructions") or "",
            })

        ui_doses = []
        for d in doses:
            taken = d.get("taken_at") or d.get("confirmed_at")
            if not taken:
                continue
            local_dt = datetime.fromisoformat(str(taken).replace("Z", "+00:00"))
            ui_doses.append({
                "id": d["id"],
                "medication_id": d.get("prescription_item_id"),
                "slot": d.get("window_name") or "dose",
                "date": local_dt.date().isoformat(),
                "taken_at": str(taken),
                "method": d.get("confirmation_method") or "dashboard",
            })

        state = dict(local)
        state["now"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        state["patient"] = {"name": user.get("name") or "Patient",
                            "caregiver": (local.get("patient") or {}).get("caregiver")}
        state["hub"] = {"connected": True, "mode": "backend"}
        state["medications"] = medications
        state["doses"] = ui_doses
        state.setdefault("reminders", [])
        state.setdefault("alerts", [])
        return state

    # ------------------------------------------------------------- actions
    def log_dose(self, item_id: str) -> None:
        """Confirm the dose that is actually due right now (her API refuses early confirms)."""
        pid = self.patient()["id"]
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        end = (now + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        doses = self._request("GET", f"/patients/{pid}/doses", params={"from": start, "to": end}).get("doses", [])
        mine = [d for d in doses if d.get("prescription_item_id") == item_id]

        def ts(value: Any) -> Optional[datetime]:
            if not value:
                return None
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None

        confirmable = []
        for d in mine:
            if d.get("status") not in ("pending", "missed", "taken_late"):
                continue
            opens, deadline = ts(d.get("on_time_start")), ts(d.get("confirm_deadline"))
            if opens and now < opens:
                continue
            if deadline and now > deadline:
                continue
            confirmable.append((opens or now, d))
        if not confirmable:
            raise DoseNotDue("This dose isn't due yet.")
        confirmable.sort(key=lambda pair: pair[0])
        self._request("POST", f"/doses/{confirmable[0][1]['id']}/confirm", json={})

    def set_count(self, item_id: str, count: float) -> None:
        item = self._item_cache.get(item_id) or {}
        med_id = (item.get("medication") or {}).get("id")
        if not med_id:
            pid = self.patient()["id"]
            item = next((i for i in self._active_items(pid) if i["id"] == item_id), None)
            med_id = ((item or {}).get("medication") or {}).get("id")
        if not med_id:
            raise BackendUnavailable("unknown medication for item")
        pid = self.patient()["id"]
        self._request("PUT", f"/patients/{pid}/inventory/{med_id}",
                      json={"quantity_remaining": float(count), "note": "count from dashboard"})

    def refill(self, item_id: str) -> None:
        pid = self.patient()["id"]
        item = self._item_cache.get(item_id)
        if item is None:
            item = next((i for i in self._active_items(pid) if i["id"] == item_id), None)
        if item is None:
            raise BackendUnavailable("unknown medication for refill")
        rx = self._request("POST", f"/patients/{pid}/refills", json={"prescription_item_id": item_id})
        refill_id = (rx.get("refill") or rx).get("id") if isinstance(rx, dict) else None
        if not refill_id:
            raise BackendUnavailable("refill request was not created")
        quantity = item.get("quantity_prescribed") or 0
        self._request("POST", f"/refills/{refill_id}/fulfill", json={"quantity_added": quantity})

    def create_from_scan(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """Add one medication by creating a NEW prescription version that keeps
        every currently active item (her model supersedes whole prescriptions)."""
        pid = self.patient()["id"]
        dose_amount = float(values.get("dose_amount") or 1)
        times = [t.strip() for t in str(values.get("schedule_times") or "").split(",") if t.strip()]

        existing = self._active_items(pid)
        items_payload: List[Dict[str, Any]] = []
        schedules: List[List[Dict[str, Any]]] = []
        for item in existing:
            item_times = [{"dose_window_id": t["dose_window_id"], "local_time": t["local_time"]}
                          for t in (item.get("schedule") or {}).get("times", []) if t.get("dose_window_id")]
            schedules.append(item_times)
            items_payload.append({
                "name": item["medication"]["name"],
                "strength": item["medication"]["strength"],
                "dose_quantity": item.get("dose_quantity", 1),
                "dose_unit": item.get("dose_unit") or "tablet",
                "quantity_prescribed": item.get("quantity_prescribed"),
                "refills_authorized": item.get("refills_authorized"),
                "instructions": item.get("instructions") or "Take as directed",
            })
        schedules.append([{"window_kind": self._nearest_kind(t), "local_time": t} for t in times])
        items_payload.append({
            "name": str(values["name"]).strip(),
            "strength": str(values["strength"]).strip(),
            "dose_quantity": _fmt_num(dose_amount),
            "dose_unit": "tablet",
            "quantity_prescribed": _fmt_num(float(values.get("quantity_start") or 0)) or None,
            "refills_authorized": (int(float(values["refills_remaining"])) if str(values.get("refills_remaining") or "").strip() else None),
            "instructions": str(values.get("instructions") or f"Take {_fmt_num(dose_amount)} as directed"),
        })

        rx = self._request("POST", f"/patients/{pid}/prescriptions", json={"items": items_payload})
        rx_id = rx.get("id") or (rx.get("prescription") or {}).get("id")
        created = rx.get("items") or (rx.get("prescription") or {}).get("items") or []
        for item, sched in zip(created, schedules):
            if sched:
                self._request("PUT", f"/prescription-items/{item['id']}/schedule", json={"times": sched})
        self._request("POST", f"/prescriptions/{rx_id}/activate")

        new_item_id = created[-1]["id"] if created else None
        item = next((i for i in self._active_items(pid) if i["id"] == new_item_id), None)
        med = (item or {}).get("medication") or {}
        return {
            "id": new_item_id,
            "name": med.get("name", values["name"]),
            "strength": med.get("strength", values["strength"]),
            "dose_amount": _fmt_num(dose_amount),
            "schedule_times": times,
            "quantity_start": int(float(values.get("quantity_start") or 0)),
            "pills_left": int(float(values.get("quantity_start") or 0)),
            "refills_remaining": (int(float(values["refills_remaining"])) if str(values.get("refills_remaining") or "").strip() else None),
            "instructions": (item or {}).get("instructions", ""),
        }

    def adherence(self, month: Optional[str]) -> Dict[str, Any]:
        pid = self.patient()["id"]
        data = self._request("GET", f"/patients/{pid}/adherence")
        days = []
        for bucket in data.get("buckets", []):
            start = str(bucket.get("bucket_start", ""))[:10]
            days.append({
                "date": start,
                "due": bucket.get("total", 0),
                "missed": bucket.get("missed", 0) + bucket.get("skipped", 0),
                "missedList": [],
                "future": start > datetime.now(timezone.utc).date().isoformat(),
            })
        month_val = month or datetime.now(timezone.utc).strftime("%Y-%m")
        return {"year": int(month_val[:4]), "month": int(month_val[5:7]) - 1, "days": days}
