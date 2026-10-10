import StatusBadge from "../../components/StatusBadge";

const WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function AdherenceCalendar({ year, month, days, selected, onSelect, onPrev, onNext, today }) {
  const lead = new Date(year, month, 1).getDay();
  const title = new Date(year, month, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
  return (
    <section aria-labelledby="cal-h" className="card flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <button type="button" aria-label="Previous month" onClick={onPrev} className="pill pill-secondary !px-4">‹</button>
        <h2 id="cal-h" className="text-xl font-bold">{title}</h2>
        <button type="button" aria-label="Next month" onClick={onNext} className="pill pill-secondary !px-4">›</button>
      </div>
      <div className="grid grid-cols-7 gap-2 text-center text-sm text-ink-soft" aria-hidden="true">
        {WEEK.map((w) => <span key={w}>{w}</span>)}
      </div>
      <div className="grid grid-cols-7 gap-2">
        {Array.from({ length: lead }, (_, i) => <span key={`b${i}`} />)}
        {days.map((d) => {
          const n = Number(d.date.slice(-2));
          const isSel = selected === d.date;
          const isToday = today === d.date;
          const empty = d.future || d.due === 0;
          const cls = empty ? "border border-dashed border-[#C3D1E3] text-ink-muted bg-white"
            : d.missed ? "bg-low-fill text-low" : "bg-ok-fill text-ok";
          const label = empty ? "upcoming" : d.missed ? `${d.missed} missed` : isToday ? "all taken so far" : "all taken";
          return (
            <button key={d.date} type="button" disabled={empty} onClick={() => onSelect(d.date)}
              aria-pressed={isSel} aria-label={`${n}, ${label}`}
              className={`flex min-h-[64px] flex-col rounded-xl p-2 text-left ${cls} ${isSel ? "outline outline-[3px] outline-offset-1 outline-[#7EA7D4]" : ""}`}>
              <span className="font-bold">{n}</span>
              <span className="text-xs">{empty ? "" : d.missed ? `${d.missed} missed` : isToday ? "Today" : "All taken"}</span>
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        <StatusBadge tone="ok">All doses taken</StatusBadge>
        <StatusBadge tone="low">One or more missed</StatusBadge>
        <StatusBadge tone="grey">Upcoming</StatusBadge>
      </div>
    </section>
  );
}
