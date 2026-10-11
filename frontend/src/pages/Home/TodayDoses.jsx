import { useState } from "react";
import Button from "../../components/Button";
import StatusBadge from "../../components/StatusBadge";
import EmptyState from "../../components/EmptyState";
import { fmtSlot, fmtTime, sameDay } from "../../lib/format";
import { api } from "../../api/client";
import { useAppState } from "../../state/AppState";

export function buildToday(data) {
  const now = new Date(data.now);
  const rows = [];
  for (const m of data.medications) {
    for (const slot of m.schedule_times) {
      const [h, mm] = slot.split(":").map(Number);
      const due = new Date(now); due.setHours(h, mm, 0, 0);
      const dose = data.doses.find((d) => d.medication_id === m.id && d.slot === slot && sameDay(d.taken_at, now));
      const reminded = data.reminders.some((r) => r.medication_id === m.id && r.slot === slot && sameDay(r.sent_at, now));
      const state = dose ? "taken" : due <= now ? (reminded ? "reminded" : "late") : "upcoming";
      rows.push({ key: `${m.id}-${slot}`, med: m, slot, due, dose, state });
    }
  }
  return rows.sort((a, b) => a.due - b.due || a.med.name.localeCompare(b.med.name));
}

const METHOD = { voice: "by voice", button: "button", dashboard: "logged by you" };

export default function TodayDoses({ data }) {
  const { run } = useAppState();
  const [busy, setBusy] = useState(null);
  const rows = buildToday(data);
  const taken = rows.filter((r) => r.state === "taken").length;
  const next = rows.find((r) => r.state === "upcoming");

  const remind = async (r) => {
    setBusy(r.key);
    try { await run(() => api.remind(r.med.id, r.slot)); } finally { setBusy(null); }
  };

  return (
    <section aria-labelledby="today-h" className="flex flex-col gap-3">
      <div>
        <h2 id="today-h" className="text-xl font-bold">Today's doses</h2>
        <p className="text-ink-soft" aria-live="polite">
          {taken} of {rows.length} doses taken.{next ? ` Next: ${fmtSlot(next.slot)}.` : ""}
        </p>
      </div>
      {rows.length === 0 ? (
        <EmptyState>No doses scheduled today.</EmptyState>
      ) : (
        <ul className="card overflow-hidden p-0">
          {rows.map((r) => (
            <li
              key={r.key}
              className={`flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line-soft px-5 py-4 last:border-b-0 ${r.state === "late" ? "bg-low-tint" : ""}`}
            >
              <span className="w-[72px] flex-none tabular-nums text-ink-soft">{fmtSlot(r.slot)}</span>
              <span className="min-w-0 flex-1"><strong>{r.med.name}</strong> {r.med.strength}</span>
              <span className="ml-auto flex flex-wrap items-center justify-end gap-2">
                {r.state === "taken" && <StatusBadge tone="ok">Taken {fmtTime(r.dose.taken_at)}, {METHOD[r.dose.method] || r.dose.method}</StatusBadge>}
                {r.state === "upcoming" && <StatusBadge tone="grey">Upcoming</StatusBadge>}
                {r.state === "reminded" && <StatusBadge tone="info">Reminder sent</StatusBadge>}
                {r.state === "late" && (
                  <>
                    <StatusBadge tone="low">Not taken yet</StatusBadge>
                    <Button
                      variant="secondary"
                      busy={busy === r.key}
                      aria-label={`Remind Rosa about ${r.med.name} at ${fmtSlot(r.slot)}`}
                      onClick={() => remind(r)}
                    >
                      Remind Rosa
                    </Button>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
