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
    let payload = null;
    try {
      payload = await res.json();
    } catch {
      /* not JSON */
    }
    const detail = payload?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d) => d.msg).join(" ")
      : detail || payload?.message || "";
    const error = new Error(message || `The MedCheck hub returned ${res.status} for ${method} ${path}.`);
    error.status = res.status; // let callers branch on 422/409 without parsing text
    error.code = typeof payload?.code === "string" ? payload.code : null;
    throw error;
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
  logDose: (id, slot, method = "dashboard") => http(`/medications/${id}/doses`, { method: "POST", body: { method, slot } }),
  skipDose: (id, slot) => http(`/medications/${id}/skip`, { method: "POST", body: { slot } }),
  // The hub identifies the bottle in the photo and compares it with what's due now.
  matchDose: (blob) => http("/doses/scan", { method: "POST", body: photoForm(blob) }),
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
