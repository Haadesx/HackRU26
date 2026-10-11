import { useState } from "react";
import { useAppState } from "../../state/AppState";
import { api } from "../../api/client";
import StatusBadge from "../../components/StatusBadge";
import EmptyState from "../../components/EmptyState";
import Button from "../../components/Button";
import { PERIODS, buildDay } from "../../lib/doses";
import { fmtLongDate, fmtSlot, fmtTime, plural } from "../../lib/format";
import DoseRow from "./DoseRow";
import DoseScanner from "./DoseScanner";

const SEGMENT = { taken: "#8FCFA5", late: "#F2CF6B", reminded: "#F2CF6B", missed: "#F2CF6B", skipped: "#C3D1E3", upcoming: "#E4ECF5" };
const MAX_BACK = 13;

export default function TrackPage() {
  const { data, run } = useAppState();
  const [back, setBack] = useState(0);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const now = new Date(data.now);
  const day = new Date(now);
  day.setDate(day.getDate() - back);
  const today = back === 0;
  const rows = buildDay(data, day);

  const count = (...states) => rows.filter((r) => states.includes(r.state)).length;
  const taken = count("taken");
  const attention = count("late", "reminded");
  const upcoming = count("upcoming");
  const missed = count("missed");
  const next = rows.find((r) => r.state === "upcoming");
  const nextGroup = next ? rows.filter((r) => r.state === "upcoming" && r.slot === next.slot) : [];
  const log = rows.filter((r) => r.state === "taken").sort((a, b) => new Date(b.dose.taken_at) - new Date(a.dose.taken_at));

  const act = async (key, kind, fn) => {
    setBusy(`${key}:${kind}`); setError(null);
    try { await run(fn); } catch (e) { setError(e.message); } finally { setBusy(null); }
  };

  const sub = today
    ? [attention && `${attention} ${attention === 1 ? "needs" : "need"} attention.`, upcoming && `${upcoming} still to come today.`].filter(Boolean).join(" ") || "Every dose today is done."
    : missed ? `${plural(missed, "dose")} missed.` : "Every dose was taken.";

  return (
    <div className="flex flex-col gap-7">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <p className="text-ink-soft">{today ? `Today, ${fmtLongDate(day)}` : fmtLongDate(day)}</p>
          <h1 className="text-[34px] font-bold leading-tight sm:text-[40px]">
            {taken} of {rows.length} medicines taken{today ? " today" : ""}
          </h1>
          <p className="text-ink-soft">{sub}</p>
        </div>
        <div className="flex items-center gap-2.5" role="group" aria-label="Choose a day">
          <button type="button" aria-label="Previous day" disabled={back >= MAX_BACK} onClick={() => setBack(back + 1)}
            className="h-11 w-11 rounded-full bg-track text-xl font-bold text-navy disabled:text-ink-muted">‹</button>
          <button type="button" onClick={() => setBack(0)} className={`min-h-[44px] rounded-full px-5 font-bold ${today ? "bg-mist text-navy" : "bg-white text-navy shadow-[inset_0_0_0_2px_#D8E3F0]"}`}>
            {today ? "Today" : "Back to today"}
          </button>
          <button type="button" aria-label="Next day" disabled={today} onClick={() => setBack(back - 1)}
            className="h-11 w-11 rounded-full bg-track text-xl font-bold text-navy disabled:text-ink-muted">›</button>
        </div>
      </header>

      {rows.length > 0 && (
        <section aria-label="Progress" className="card flex flex-col gap-3.5 p-5 sm:p-6">
          <div role="img" aria-label={`${taken} taken, ${attention + missed} not taken, ${upcoming} upcoming`} className="flex gap-1">
            {rows.map((r, i) => (
              <span key={r.key} className={`h-7 flex-1 ${i === 0 ? "rounded-l-full" : ""} ${i === rows.length - 1 ? "rounded-r-full" : ""}`}
                style={{ background: `linear-gradient(180deg, rgba(255,255,255,.55), rgba(255,255,255,0) 55%), ${SEGMENT[r.state]}` }} />
            ))}
          </div>
          <div className="flex flex-wrap gap-2.5">
            <StatusBadge tone="ok">{taken} taken</StatusBadge>
            {today && attention > 0 && <StatusBadge tone="low">{attention} not taken yet</StatusBadge>}
            {missed > 0 && <StatusBadge tone="low">{missed} missed</StatusBadge>}
            {count("skipped") > 0 && <StatusBadge tone="grey">{count("skipped")} skipped</StatusBadge>}
            {today && upcoming > 0 && <StatusBadge tone="grey">{upcoming} coming up</StatusBadge>}
          </div>
        </section>
      )}

      {error && <p role="alert" className="rounded-2xl bg-urgent-tint px-4 py-3 font-bold text-urgent">{error}</p>}

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-6">
          {rows.length === 0 && <EmptyState action={<Button to="/scan">Scan a bottle</Button>}>No medications are scheduled. Scan a bottle to add one.</EmptyState>}
          {PERIODS.map((p) => {
            const group = rows.filter((r) => r.period === p.key);
            if (!group.length) return null;
            const done = group.filter((r) => r.state === "taken" || r.state === "skipped").length;
            const times = [...new Set(group.map((r) => r.slot))].map(fmtSlot).join(", ");
            return (
              <section key={p.key} aria-labelledby={`p-${p.key}`} className="flex flex-col gap-2.5">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <h2 id={`p-${p.key}`} className="text-[22px] font-bold">{p.label} <span className="font-normal text-ink-soft">{times}</span></h2>
                  <span className={`font-bold ${done === group.length ? "text-ok" : "text-ink-soft"}`}>{done} of {group.length} done</span>
                </div>
                <ul className="card overflow-hidden p-0">
                  {group.map((r) => (
                    <DoseRow key={r.key} row={r} now={now} actionable={today}
                      busy={busy?.startsWith(`${r.key}:`) ? busy.split(":")[1] : null}
                      onTake={() => act(r.key, "take", () => api.logDose(r.med.id, r.slot, "dashboard"))}
                      onRemind={() => act(r.key, "remind", () => api.remind(r.med.id, r.slot))}
                      onSkip={() => act(r.key, "skip", () => api.skipDose(r.med.id, r.slot))} />
                  ))}
                </ul>
              </section>
            );
          })}
        </div>

        <aside className="flex flex-col gap-5">
          {today && <DoseScanner />}
          {today && next && (
            <section aria-labelledby="next-h" className="flex flex-col gap-1 rounded-card bg-mist p-5">
              <h2 id="next-h" className="font-bold text-ink-soft">Coming up next</h2>
              <strong className="text-[26px] text-navy">{fmtSlot(next.slot)}</strong>
              <span>{nextGroup.map((r) => r.med.name).join(" and ")}. Hold each bottle up to the scanner when it's time.</span>
            </section>
          )}
          <section aria-labelledby="log-h" className="card p-5">
            <h2 id="log-h" className="mb-1.5 text-lg font-bold">Taken {today ? "today" : "this day"}</h2>
            {log.length === 0 ? <p className="text-ink-soft">Nothing yet.</p> : (
              <ul>
                {log.map((r) => (
                  <li key={r.key} className="flex justify-between gap-3 border-b border-line-soft py-2.5 last:border-b-0">
                    <span>{r.med.name}</span><span className="text-ink-soft">{fmtTime(r.dose.taken_at)}</span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-2.5 text-[15px] text-ink-soft">Newest first. Logged by the scanner, Rosa&apos;s wearable, or you.</p>
          </section>
          <section aria-labelledby="how-h" className="card flex flex-col gap-2 p-5">
            <h2 id="how-h" className="text-lg font-bold">How each dose is decided</h2>
            <p><strong className="text-ok">Taken:</strong> the scanner matched the bottle and someone pressed Rosa took it, or you pressed Mark as taken.</p>
            <p><strong className="text-low">Not taken yet or missed:</strong> the dose time passed with no confirmed dose.</p>
            <p><strong className="text-ink-soft">Skipped:</strong> someone chose Skip on purpose, for example on a doctor&apos;s advice.</p>
            <p className="text-[15px] text-ink-soft">Seeing the bottle alone never counts as taken. Rosa might pick it up and put it back.</p>
          </section>
        </aside>
      </div>
    </div>
  );
}
