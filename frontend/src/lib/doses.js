// Works out every scheduled dose for one day and its state. Shared by Home and Track.
import { sameDay } from "./format";

export const PERIODS = [
  { key: "morning", label: "Morning", from: 0, to: 12 },
  { key: "afternoon", label: "Afternoon", from: 12, to: 17 },
  { key: "evening", label: "Evening", from: 17, to: 24 },
];

export const periodOf = (slot) => {
  const h = Number(slot.slice(0, 2));
  return PERIODS.find((p) => h >= p.from && h < p.to).key;
};

/**
 * state: "taken" | "skipped" | "late" (due today, not taken) | "reminded" | "missed" (past day) | "upcoming"
 */
export function buildDay(data, day = data.now) {
  const now = new Date(data.now);
  const date = new Date(day);
  const today = sameDay(date, now);
  const rows = [];
  for (const m of data.medications) {
    for (const slot of m.schedule_times) {
      const [h, mm] = slot.split(":").map(Number);
      const due = new Date(date);
      due.setHours(h, mm, 0, 0);
      const dose = data.doses.find((d) => d.medication_id === m.id && d.slot === slot && sameDay(d.taken_at, date));
      const skip = (data.skips || []).find((s) => s.medication_id === m.id && s.slot === slot && sameDay(s.at, date));
      const reminded = (data.reminders || []).some((r) => r.medication_id === m.id && r.slot === slot && sameDay(r.sent_at, date));
      let state = "upcoming";
      if (dose) state = "taken";
      else if (skip) state = "skipped";
      else if (due <= now) state = today ? (reminded ? "reminded" : "late") : "missed";
      rows.push({ key: `${m.id}-${slot}`, med: m, slot, due, dose, skip, state, period: periodOf(slot) });
    }
  }
  return rows.sort((a, b) => a.due - b.due || a.med.name.localeCompare(b.med.name));
}

/** The dose most likely in Rosa's hand right now: overdue first, then the next one due. */
export function doseDueNow(data) {
  const rows = buildDay(data).filter((r) => r.state === "late" || r.state === "reminded" || r.state === "upcoming");
  return rows[0] || null;
}

export const METHOD = { voice: "by voice", button: "button", dashboard: "logged by you", scan: "scanned" };
