import { useEffect, useState } from "react";
import Button from "../../components/Button";
import { api } from "../../api/client";
import { useAppState } from "../../state/AppState";
import { fmtLongDate, fmtSlot, fmtTime, sameDay } from "../../lib/format";
import AdherenceCalendar from "./AdherenceCalendar";

const keyOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export default function HistoryPage() {
  const { data } = useAppState();
  const now = new Date(data.now);
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() });
  const [adh, setAdh] = useState(null);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    api.getAdherence(ym.y, ym.m).then((a) => {
      setAdh(a);
      const firstMissed = [...a.days].reverse().find((d) => d.missed);
      setSelected(firstMissed?.date ?? null);
    });
  }, [ym.y, ym.m, data]);

  const move = (delta) => setYm(({ y, m }) => { const d = new Date(y, m + delta, 1); return { y: d.getFullYear(), m: d.getMonth() }; });
  if (!adh) return <p role="status" className="text-ink-soft">Loading history…</p>;

  const evening = adh.days.flatMap((d) => d.missedList).filter((x) => Number(x.slot.slice(0, 2)) >= 17).length;
  const dayData = adh.days.find((d) => d.date === selected);
  const dayDate = selected ? new Date(`${selected}T12:00`) : null;

  const rows = dayDate ? data.medications.flatMap((m) => m.schedule_times.map((slot) => {
    const dose = data.doses.find((d) => d.medication_id === m.id && d.slot === slot && sameDay(d.taken_at, dayDate));
    return { key: `${m.id}-${slot}`, name: m.name, slot, dose };
  })).sort((a, b) => a.slot.localeCompare(b.slot)) : [];

  const download = () => {
    const lines = [`MedCheck adherence report, ${new Date(adh.year, adh.month, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" })}`,
      `${data.patient.name} took ${adh.taken} of ${adh.due} doses.`, "",
      ...adh.days.filter((d) => d.missed).map((d) => `${d.date}: missed ${d.missedList.map((x) => `${x.name} at ${fmtSlot(x.slot)}`).join(", ")}`)];
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/plain" }));
    const a = document.createElement("a"); a.href = url; a.download = `medcheck-report-${adh.year}-${adh.month + 1}.txt`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-7">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div>
          <h1 className="text-[38px] font-bold leading-tight">
            {adh.due ? `${data.patient.name} took ${adh.taken} of ${adh.due} doses this month` : "No doses recorded this month"}
          </h1>
          {adh.missed > 0 && (
            <p className="text-ink-soft">
              {adh.missed} missed {adh.missed === 1 ? "dose" : "doses"}{evening === adh.missed ? ", all in the evening." : evening ? `, ${evening} in the evening.` : "."}
            </p>
          )}
        </div>
        <Button variant="secondary" onClick={download} disabled={!adh.due}>Download report for her doctor</Button>
      </header>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)] xl:gap-10">
        <AdherenceCalendar year={adh.year} month={adh.month} days={adh.days} selected={selected} onSelect={setSelected}
          onPrev={() => move(-1)} onNext={() => move(1)} today={keyOf(now)} />
        <aside className="flex flex-col gap-4 xl:sticky xl:top-8">
          {dayData ? (
            <section aria-labelledby="day-h" className="flex flex-col gap-3">
              <h2 id="day-h" className="text-xl font-bold">{fmtLongDate(dayDate)}</h2>
              <ul className="card overflow-hidden p-0">
                {rows.map((r) => {
                  const [h, mm] = r.slot.split(":").map(Number);
                  const due = new Date(dayDate); due.setHours(h, mm, 0, 0);
                  const future = due > now;
                  return (
                    <li key={r.key} className={`flex justify-between gap-3 border-b border-line-soft px-4 py-3 last:border-b-0 ${!r.dose && !future ? "bg-low-tint" : ""}`}>
                      <span>{r.name}, {fmtSlot(r.slot)}</span>
                      <span className={`font-bold ${r.dose ? "text-ok" : future ? "text-ink-soft" : "text-low"}`}>{r.dose ? fmtTime(r.dose.taken_at) : future ? "Upcoming" : "Missed"}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : (
            <p className="text-ink-soft">Pick a day to see its doses.</p>
          )}
          {evening > 0 && (
            <div className="rounded-2xl bg-mist px-5 py-4">
              <strong className="text-navy">Something to try</strong>
              <p>Evening doses are missed most often. A second reminder 30 minutes later could help.</p>
              <Button to="/settings" variant="secondary" className="mt-2">Change reminders</Button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
