// Supply math shared by every screen. Mirror this in the backend.
export const DAY_MS = 86_400_000;
export const DEFAULT_THRESHOLDS = { first: 7, second: 5, urgent: 3 };

export const pillsPerDay = (m) => m.dose_amount * m.doses_per_day;

export function daysLeft(m) {
  const perDay = pillsPerDay(m);
  return perDay > 0 ? Math.max(0, m.pills_left) / perDay : Infinity;
}

export function statusOf(m, t = DEFAULT_THRESHOLDS) {
  const d = daysLeft(m);
  if (d <= t.urgent) return "urgent";
  if (d <= t.first) return "low";
  return "ok";
}

export const STATUS = {
  ok: { label: "On track", text: "text-ok", fill: "bg-ok-fill", tint: "bg-ok-tint", pill: ["#8FCFA5", "#DCF1E3"] },
  low: { label: "Refill soon", text: "text-low", fill: "bg-low-fill", tint: "bg-low-tint", pill: ["#F2CF6B", "#FCEFCC"] },
  urgent: { label: "Refill now", text: "text-urgent", fill: "bg-urgent-fill", tint: "bg-urgent-tint", pill: ["#EE9A8E", "#FBDCD6"] },
};

export function runOutDate(m, now) {
  return new Date(new Date(now).getTime() + Math.floor(daysLeft(m)) * DAY_MS);
}

export const sortByUrgency = (meds) => [...meds].sort((a, b) => daysLeft(a) - daysLeft(b));

/** 24 pills = a full bottle = 30 days or more. */
export const pillCount = (m) => Math.ceil((Math.min(daysLeft(m), 30) / 30) * 24);
