// In-memory demo backend. Same function names and shapes as client.js's real calls,
// so the UI never knows which one it is talking to.
import { daysLeft, DAY_MS } from "../lib/inventory";

const clone = (x) => structuredClone(x);
let nextId = 1000;
const id = () => nextId++;
const iso = (d) => new Date(d).toISOString();
const dateKey = (d) => {
  const x = new Date(d);
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
};
const at = (day, hhmm, plusMin = 0) => {
  const [h, m] = hhmm.split(":").map(Number);
  return new Date(2026, 9, day, h, m + plusMin);
};

const CVS = { pharmacy_name: "CVS Pharmacy", pharmacy_phone: "(732) 555-0123" };

function seedMedications() {
  return [
    { id: 1, name: "Lisinopril", strength: "10 mg", purpose: "for blood pressure", dose_amount: 1, doses_per_day: 1,
      schedule_times: ["08:00"], quantity_start: 30, pills_left: 29, refills_remaining: 2, fill_date: "2026-10-09",
      instructions: "Take 1 tablet daily", prescriber: "Dr. Patel", prescriber_phone: "(732) 555-0170", ...CVS, confidence: {} },
    { id: 2, name: "Metformin", strength: "500 mg", purpose: "for diabetes", dose_amount: 1, doses_per_day: 2,
      schedule_times: ["08:00", "20:00"], quantity_start: 60, pills_left: 22, refills_remaining: 1, fill_date: "2026-09-21",
      instructions: "Take 1 tablet twice daily with food", prescriber: "Dr. Patel", prescriber_phone: "(732) 555-0170", ...CVS, confidence: {} },
    { id: 3, name: "Atorvastatin", strength: "20 mg", purpose: "for cholesterol", dose_amount: 1, doses_per_day: 1,
      schedule_times: ["20:00"], quantity_start: 30, pills_left: 2, refills_remaining: 0, fill_date: "2026-09-19",
      instructions: "Take 1 tablet at bedtime", prescriber: "Dr. Okafor", prescriber_phone: "(732) 555-0144", ...CVS,
      confidence: { prescriber: "unsure" } },
    { id: 4, name: "Amlodipine", strength: "5 mg", purpose: "for blood pressure", dose_amount: 1, doses_per_day: 1,
      schedule_times: ["08:00"], quantity_start: 90, pills_left: 64, refills_remaining: 3, fill_date: "2026-09-14",
      instructions: "Take 1 tablet daily", prescriber: "Dr. Patel", prescriber_phone: "(732) 555-0170", ...CVS, confidence: {} },
    { id: 5, name: "Vitamin D3", strength: "1000 IU", purpose: "supplement", dose_amount: 1, doses_per_day: 1,
      schedule_times: ["08:00"], quantity_start: 100, pills_left: 4, refills_remaining: null, otc: true, fill_date: "2026-07-06",
      instructions: "Take 1 tablet daily", prescriber: "", prescriber_phone: "", pharmacy_name: "Over the counter",
      pharmacy_phone: "", confidence: {} },
  ];
}

function seedDoses(meds, now) {
  const missed = new Set(["3|2|20:00", "7|2|20:00", "7|3|20:00", "10|5|08:00"]);
  const methods = ["voice", "button", "voice"];
  const doses = [];
  let k = 0;
  for (let day = 1; day <= now.getDate(); day++) {
    for (const m of meds) {
      for (const slot of m.schedule_times) {
        const when = at(day, slot, 4 + ((day * 7 + m.id * 3) % 18));
        if (when > now || missed.has(`${day}|${m.id}|${slot}`)) continue;
        doses.push({ id: id(), medication_id: m.id, slot, date: dateKey(when), taken_at: iso(when), method: methods[k++ % 3] });
      }
    }
  }
  return doses;
}

const FIELD_ORDER = ["name", "strength", "dose_amount", "schedule_times", "quantity_start", "refills_remaining",
  "pharmacy_name", "pharmacy_phone", "prescriber"];

function emptyFields() {
  return Object.fromEntries(FIELD_ORDER.map((k) => [k, { value: "", state: "missing" }]));
}

function seed() {
  const now = new Date(2026, 9, 10, 14, 30);
  const medications = seedMedications();
  const losartan = emptyFields();
  Object.assign(losartan, {
    name: { value: "Losartan", state: "filled" },
    strength: { value: "25 mg", state: "filled" },
    dose_amount: { value: "1", state: "filled" },
    schedule_times: { value: "08:00", state: "filled" },
    pharmacy_name: { value: "CVS Pharmacy", state: "filled" },
    pharmacy_phone: { value: "(732) 555-0123", state: "filled" },
    prescriber: { value: "Dr. Pat?l", state: "unsure" },
  });
  return {
    now: iso(now),
    patient: { name: "Rosa", caregiver: "Elena" },
    hub: { connected: true },
    medications,
    doses: seedDoses(medications, now),
    reminders: [],
    skips: [],
    alerts: [
      { id: id(), medication_id: 3, type: "no_refills", sent_at: iso(at(9, "09:00")),
        message: "No refills left for Atorvastatin. Dr. Okafor needs to send a new prescription." },
      { id: id(), medication_id: 5, type: "low_5", sent_at: iso(at(10, "07:00")),
        message: "Rosa has about 4 days of Vitamin D3 left." },
    ],
    events: [
      { id: id(), type: "wrong_bottle", at: iso(at(10, "07:59")),
        message: "Rosa picked up Metformin when Lisinopril was due. MedCheck stopped her before she took it." },
    ],
    scans: [
      { id: 501, status: "needs_caregiver", photos: 2, fields: losartan, created_at: iso(at(10, "14:10")),
        history: [
          { step: "Scanned", at: iso(at(10, "14:10")), detail: "Read 7 of 9 details." },
          { step: "Asked Rosa", at: iso(at(10, "14:11")), detail: "\u201cHow many tablets came in this bottle?\u201d" },
          { step: "Rosa wasn't sure", at: iso(at(10, "14:13")), detail: "She said \u201cI don't know.\u201d" },
          { step: "Sent to you", at: iso(at(10, "14:14")), detail: "Waiting for you now." },
        ] },
    ],
    settings: {
      thresholds: { first: 7, second: 5, urgent: 3 },
      alert_missed: true,
      alert_no_refills: true,
      alert_wrong_bottle: false,
      remind_again: "30",
      voice_language: "English",
      camera_paused: false,
      caregivers: [
        { id: 1, name: "Elena", phone: "(732) 555-0187", scope: "all", you: true },
        { id: 2, name: "Marco", phone: "(908) 555-0142", scope: "refills" },
      ],
    },
  };
}

let db = seed();
const delay = (ms = 150) => new Promise((r) => setTimeout(r, ms));
const med = (mid) => {
  const m = db.medications.find((x) => x.id === Number(mid));
  if (!m) throw new Error("That medication no longer exists.");
  return m;
};

function alerted(mid, type) {
  return db.alerts.some((a) => a.medication_id === mid && a.type === type);
}
function pushAlert(m, type, message) {
  db.alerts.unshift({ id: id(), medication_id: m.id, type, message, sent_at: db.now });
}
function checkSupply(m) {
  const t = db.settings.thresholds;
  if (m.refills_remaining === 0 && !alerted(m.id, "no_refills") && db.settings.alert_no_refills) {
    pushAlert(m, "no_refills", `No refills left for ${m.name}. ${m.prescriber || "The doctor"} needs to send a new prescription.`);
  }
  const d = daysLeft(m);
  for (const [key, limit] of [["low_3", t.urgent], ["low_5", t.second], ["low_7", t.first]]) {
    if (d <= limit) {
      if (!alerted(m.id, key)) {
        const left = Math.floor(d);
        pushAlert(m, key, left <= 0 ? `Rosa is out of ${m.name}.` : `Rosa has about ${left} days of ${m.name} left.`);
      }
      break;
    }
  }
}
function take(m, slot, when, method) {
  if (m.pills_left < m.dose_amount) return false;
  m.pills_left -= m.dose_amount;
  db.doses.push({ id: id(), medication_id: m.id, slot, date: dateKey(when), taken_at: iso(when), method });
  return true;
}

// Simulated label reading: each photo of the demo bottle reveals more of the label.
const DEMO_BOTTLE = {
  name: "Furosemide", strength: "20 mg", dose_amount: "1", schedule_times: "08:00", quantity_start: "30",
  refills_remaining: "3", pharmacy_name: "CVS Pharmacy", pharmacy_phone: "(732) 555-0123", prescriber: "Dr. Patel",
};
const REVEAL = [
  ["name", "strength", "dose_amount", "schedule_times", "pharmacy_name"],
  ["pharmacy_phone", "quantity_start"],
  ["refills_remaining"],
];
function readPhoto(scan) {
  const step = REVEAL[Math.min(scan.photos - 1, REVEAL.length - 1)];
  for (const k of step) scan.fields[k] = { value: DEMO_BOTTLE[k], state: "filled" };
  if (scan.photos === 1) scan.fields.prescriber = { value: "Dr. Pat?l", state: "unsure" };
  if (scan.photos >= 3) scan.fields.prescriber = { value: DEMO_BOTTLE.prescriber, state: "filled" };
}

export const mock = {
  async health() { await delay(50); return { ok: db.hub.connected }; },
  async getState() { await delay(); return clone(db); },

  async logDose(mid, slot, method = "dashboard") {
    await delay();
    const m = med(mid);
    const today = dateKey(db.now);
    const taken = db.doses.filter((d) => d.medication_id === m.id && d.date === today).map((d) => d.slot);
    const s = slot || m.schedule_times.find((t) => !taken.includes(t)) || m.schedule_times[0];
    if (slot && db.doses.some((d) => d.medication_id === m.id && d.date === today && d.slot === s)) {
      throw new Error(`${m.name} was already taken at this time today.`);
    }
    if (!take(m, s, db.now, method)) throw new Error(`There are no ${m.name} pills left to log.`);
    checkSupply(m);
    return clone(db);
  },

  async skipDose(mid, slot) {
    await delay();
    const m = med(mid);
    db.skips.push({ medication_id: m.id, slot, at: db.now });
    return clone(db);
  },

  /**
   * Dose scanner. The real hub reads the photo; the mock pretends the bottle is
   * `demoMedId` (or the dose due now) and reports whether it's the right one.
   * Returns { status: "match" | "wrong_bottle" | "already_taken" | "not_scheduled", ... }
   */
  async matchDose(_photo, demoMedId) {
    await delay(500);
    const now = new Date(db.now);
    const today = dateKey(now);
    const slotState = (m, slot) => {
      const [h, mm] = slot.split(":").map(Number);
      const due = new Date(now); due.setHours(h, mm, 0, 0);
      const taken = db.doses.find((d) => d.medication_id === m.id && d.date === today && d.slot === slot);
      const skipped = db.skips.some((x) => x.medication_id === m.id && x.slot === slot && dateKey(x.at) === today);
      return { m, slot, due, taken, skipped };
    };
    const open = db.medications.flatMap((m) => m.schedule_times.map((t) => slotState(m, t)))
      .filter((x) => !x.taken && !x.skipped)
      .sort((a, b) => Math.abs(a.due - now) - Math.abs(b.due - now));
    const expected = open.find((x) => x.due <= now) || open[0] || null;
    const seen = demoMedId ? med(demoMedId) : expected?.m;
    if (!seen) return { status: "not_scheduled", message: "No doses are left today." };
    const mine = seen.schedule_times.map((t) => slotState(seen, t));
    const openMine = mine.filter((x) => !x.taken && !x.skipped).sort((a, b) => Math.abs(a.due - now) - Math.abs(b.due - now))[0];
    const base = { medication_id: seen.id, name: seen.name, strength: seen.strength };
    if (!openMine) {
      const last = mine.filter((x) => x.taken).at(-1);
      return { ...base, status: "already_taken", taken_at: last?.taken.taken_at, slot: last?.slot };
    }
    if (expected && expected.m.id !== seen.id && openMine.due > now) {
      db.events.unshift({ id: id(), type: "wrong_bottle", at: db.now,
        message: `Picked up ${seen.name} when ${expected.m.name} was due. MedCheck caught it before it was taken.` });
      return { ...base, status: "wrong_bottle", expected: { medication_id: expected.m.id, name: expected.m.name, slot: expected.slot } };
    }
    return { ...base, status: "match", slot: openMine.slot, late: openMine.due <= now };
  },

  async remind(mid, slot) {
    await delay();
    db.reminders.push({ medication_id: Number(mid), slot, date: dateKey(db.now), sent_at: db.now });
    return clone(db);
  },

  async recordCount(mid, count) {
    await delay();
    const m = med(mid);
    m.pills_left = Number(count);
    checkSupply(m);
    return clone(db);
  },

  async markRefilled(mid) {
    await delay();
    const m = med(mid);
    m.pills_left += m.quantity_start;
    if (m.refills_remaining) m.refills_remaining -= 1;
    m.fill_date = dateKey(db.now);
    db.alerts = db.alerts.filter((a) => !(a.medication_id === m.id && a.type.startsWith("low_")));
    return clone(db);
  },

  async updateMedication(mid, patch) {
    await delay();
    const m = med(mid);
    const { schedule_times: times, ...rest } = patch;
    Object.assign(m, rest);
    if (times) {
      // Same shape the real hub accepts: ["08:00", "20:00"] or "08:00, 20:00".
      const list = (Array.isArray(times) ? times : String(times).split(",")).map((t) => t.trim()).filter(Boolean);
      if (!list.length) throw new Error("Add at least one time of day, like 08:00.");
      m.schedule_times = [...new Set(list)].sort();
      m.doses_per_day = m.schedule_times.length;
    }
    m.confidence = {};
    return clone(db);
  },

  async stopTracking(mid) {
    await delay();
    db.medications = db.medications.filter((m) => m.id !== Number(mid));
    return clone(db);
  },

  // ---- Scanning ----
  async startScan() {
    await delay(500);
    const scan = { id: id(), status: "reading", photos: 1, fields: emptyFields(), created_at: db.now,
      history: [{ step: "Scanned", at: db.now, detail: "First photo taken." }] };
    readPhoto(scan);
    db.scans.push(scan);
    return clone(scan);
  },
  async startManual() {
    await delay();
    const scan = { id: id(), status: "reading", photos: 0, fields: emptyFields(), created_at: db.now, manual: true, history: [] };
    db.scans.push(scan);
    return clone(scan);
  },
  async addPhoto(scanId) {
    await delay(500);
    const scan = db.scans.find((s) => s.id === Number(scanId));
    scan.photos += 1;
    readPhoto(scan);
    return clone(scan);
  },
  async getScan(scanId) {
    await delay();
    const scan = db.scans.find((s) => s.id === Number(scanId));
    if (!scan) throw new Error("That scan couldn't be found.");
    return clone(scan);
  },
  async discardScan(scanId) {
    await delay();
    db.scans = db.scans.filter((s) => s.id !== Number(scanId));
    return clone(db);
  },
  async completeScan(scanId, values) {
    await delay(600);
    const scan = db.scans.find((s) => s.id === Number(scanId));
    if (!scan || scan.status === "complete") throw new Error("This medication was already added.");
    const times = String(values.schedule_times).split(",").map((t) => t.trim()).filter(Boolean);
    const m = {
      id: id(), name: values.name, strength: values.strength, purpose: "",
      dose_amount: Number(values.dose_amount) || 1, doses_per_day: times.length || 1, schedule_times: times,
      quantity_start: Number(values.quantity_start), pills_left: Number(values.quantity_start),
      refills_remaining: values.refills_remaining === "" ? null : Number(values.refills_remaining),
      fill_date: dateKey(db.now), instructions: `Take ${values.dose_amount || 1} tablet daily`,
      prescriber: values.prescriber, prescriber_phone: "", pharmacy_name: values.pharmacy_name,
      pharmacy_phone: values.pharmacy_phone, confidence: {},
    };
    db.medications.push(m);
    scan.status = "complete";
    scan.medication_id = m.id;
    checkSupply(m);
    return { medication: clone(m) };
  },

  // ---- History ----
  async getAdherence(year, month) {
    await delay();
    const now = new Date(db.now);
    const last = new Date(year, month + 1, 0).getDate();
    const days = [];
    for (let d = 1; d <= last; d++) {
      const date = new Date(year, month, d);
      const key = dateKey(date);
      let due = 0;
      const missedList = [];
      for (const m of db.medications) {
        for (const slot of m.schedule_times) {
          const [h, mm] = slot.split(":").map(Number);
          const when = new Date(year, month, d, h, mm);
          if (when > now) continue;
          due++;
          const hit = db.doses.some((x) => x.medication_id === m.id && x.date === key && x.slot === slot)
            || db.skips.some((x) => x.medication_id === m.id && x.slot === slot && dateKey(x.at) === key);
          if (!hit) missedList.push({ medication_id: m.id, name: m.name, slot });
        }
      }
      const future = date > now && !(date.toDateString() === now.toDateString());
      days.push({ date: key, due, missed: missedList.length, missedList, future });
    }
    const due = days.reduce((a, x) => a + x.due, 0);
    const missed = days.reduce((a, x) => a + x.missed, 0);
    return { year, month, days, due, taken: due - missed, missed };
  },

  // ---- Settings ----
  async saveSettings(next) {
    await delay();
    db.settings = clone(next);
    return clone(db);
  },
  async exportData() {
    await delay();
    return new Blob([JSON.stringify(db, null, 2)], { type: "application/json" });
  },
  async deleteAll() {
    await delay();
    const settings = db.settings;
    db = { ...seed(), medications: [], doses: [], alerts: [], events: [], scans: [], settings };
    return clone(db);
  },

  // ---- Demo controls ----
  async advanceDays(n) {
    await delay();
    const start = new Date(db.now);
    for (let i = 1; i <= n; i++) {
      const day = new Date(start.getTime() + i * DAY_MS);
      for (const m of db.medications) {
        for (const slot of m.schedule_times) {
          const [h, mm] = slot.split(":").map(Number);
          const when = new Date(day); when.setHours(h, mm + 6, 0, 0);
          db.now = iso(when);
          take(m, slot, when, "voice");
        }
        checkSupply(m);
      }
    }
    db.now = iso(new Date(start.getTime() + n * DAY_MS));
    db.reminders = [];
    return clone(db);
  },
  async reset() { await delay(); db = seed(); return clone(db); },
};
