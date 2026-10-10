export const fmtDate = (d) =>
  new Date(d).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

export const fmtLongDate = (d) =>
  new Date(d).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });

export const fmtTime = (d) =>
  new Date(d).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

export const fmtSlot = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return fmtTime(new Date(2000, 0, 1, h, m));
};

export const sameDay = (a, b) => new Date(a).toDateString() === new Date(b).toDateString();

export function relativeDay(iso, now) {
  const d = new Date(iso);
  if (sameDay(d, now)) return `Today, ${fmtTime(d)}`;
  const y = new Date(now);
  y.setDate(y.getDate() - 1);
  if (sameDay(d, y)) return `Yesterday, ${fmtTime(d)}`;
  return `${fmtDate(d)}, ${fmtTime(d)}`;
}

export function greeting(now) {
  const h = new Date(now).getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
