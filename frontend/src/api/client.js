// The one contract between the UI and the backend. Every screen calls these functions;
// with VITE_API_URL unset they run against the in-memory mock.
import { mock } from "./mock";

const BASE = import.meta.env.VITE_API_URL?.replace(/\/$/, "");
export const usingMock = !BASE;

async function http(path, { method = "GET", body, raw } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body && !(body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    // FastAPI sends {"detail": "..."}; validation errors send {"detail": [{ "msg": "..." }]}.
    let message = "";
    try {
      const body = await res.json();
      message = Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join(" ") : body.detail || body.message || "";
    } catch {
      /* not JSON */
    }
    throw new Error(message || `The MedCheck hub returned ${res.status} for ${method} ${path}.`);
  }
  return raw ? res.blob() : res.json();
}

const photoForm = (blob) => {
  const f = new FormData();
  f.append("photo", blob, "label.jpg");
  return f;
};

const real = {
  health: () => http("/health"),
  getState: () => http("/state"),
  logDose: (id, slot) => http(`/medications/${id}/doses`, { method: "POST", body: { method: "dashboard", slot } }),
  remind: (id, slot) => http(`/medications/${id}/remind`, { method: "POST", body: { slot } }),
  recordCount: (id, count) => http(`/medications/${id}/counts`, { method: "POST", body: { count } }),
  markRefilled: (id) => http(`/medications/${id}/refill`, { method: "POST" }),
  updateMedication: (id, patch) => http(`/medications/${id}`, { method: "PATCH", body: patch }),
  stopTracking: (id) => http(`/medications/${id}`, { method: "DELETE" }),
  startScan: (blob) => http("/scans", { method: "POST", body: photoForm(blob) }),
  startManual: () => http("/scans", { method: "POST", body: { manual: true } }),
  addPhoto: (scanId, blob) => http(`/scans/${scanId}/photos`, { method: "POST", body: photoForm(blob) }),
  getScan: (scanId) => http(`/scans/${scanId}`),
  discardScan: (scanId) => http(`/scans/${scanId}`, { method: "DELETE" }),
  completeScan: (scanId, values) => http(`/scans/${scanId}/complete`, { method: "POST", body: values }),
  getAdherence: (year, month) => http(`/adherence?month=${year}-${String(month + 1).padStart(2, "0")}`),
  saveSettings: (s) => http("/settings", { method: "PUT", body: s }),
  exportData: () => http("/export", { raw: true }),
  deleteAll: () => http("/data", { method: "DELETE" }),
  advanceDays: (days) => http("/demo/advance", { method: "POST", body: { days } }),
  reset: () => http("/demo/reset", { method: "POST" }),
};

export const api = usingMock ? mock : real;
