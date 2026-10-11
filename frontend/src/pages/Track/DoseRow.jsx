import { useState } from "react";
import Button from "../../components/Button";
import StatusBadge from "../../components/StatusBadge";
import { METHOD } from "../../lib/doses";
import { fmtTime } from "../../lib/format";
import { daysLeft } from "../../lib/inventory";

const CAPSULE = {
  taken: ["#8FCFA5", "#DCF1E3"],
  late: ["#F2CF6B", "#FCEFCC"],
  reminded: ["#F2CF6B", "#FCEFCC"],
  missed: ["#F2CF6B", "#FCEFCC"],
  skipped: ["#C3D1E3", "#ECEFF4"],
  upcoming: ["#C3D1E3", "#ECEFF4"],
};

function lateBy(due, now) {
  const mins = Math.round((now - due) / 60000);
  if (mins < 60) return `${mins} min late`;
  const h = Math.floor(mins / 60);
  return `${h} ${h === 1 ? "hour" : "hours"} late`;
}

/** One scheduled dose: what it is, whether it was taken, and what the caregiver can do. */
export default function DoseRow({ row, now, actionable, busy, onTake, onRemind, onSkip }) {
  const [confirmSkip, setConfirmSkip] = useState(false);
  const { med, state, dose, due } = row;
  const [c1, c2] = CAPSULE[state];
  const open = actionable && ["late", "reminded", "upcoming"].includes(state);
  const lowSupply = daysLeft(med) <= 3 && state !== "taken";
  const tint = state === "late" || state === "missed" ? "bg-low-tint" : "bg-white";

  return (
    <li className={`flex flex-wrap items-center gap-4 border-b border-line-soft px-5 py-4 last:border-b-0 ${tint}`}>
      <span aria-hidden="true" className="h-5 w-10 flex-none rounded-full shadow-[0_0_0_1px_rgba(31,58,104,.12)]"
        style={{ background: `linear-gradient(180deg, rgba(255,255,255,.55), rgba(255,255,255,0) 55%), linear-gradient(90deg, ${c1} 50%, ${c2} 50%)` }} />
      <div className="min-w-[10rem] flex-1">
        <strong className="text-lg">{med.name}</strong> <span className="text-ink-soft">{med.strength}</span>
        {med.purpose && <div className="text-[15px] text-ink-soft">{med.purpose}</div>}
        {lowSupply && <div className="text-sm font-bold text-urgent">Only {Math.max(0, Math.round(med.pills_left))} pills left. Refill needed.</div>}
      </div>
      <div className="flex flex-wrap items-center justify-end gap-2.5">
        {state === "taken" && <StatusBadge tone="ok">Taken {fmtTime(dose.taken_at)}, {METHOD[dose.method] || dose.method}</StatusBadge>}
        {state === "skipped" && <StatusBadge tone="grey">Skipped</StatusBadge>}
        {state === "missed" && <StatusBadge tone="low">Missed</StatusBadge>}
        {state === "late" && <StatusBadge tone="low">{lateBy(due, now)}</StatusBadge>}
        {state === "reminded" && <StatusBadge tone="info">Reminder sent</StatusBadge>}
        {state === "upcoming" && <StatusBadge tone="grey">Upcoming</StatusBadge>}
        {open && !confirmSkip && (
          <>
            {state === "late" && <Button variant="secondary" busy={busy === "remind"} onClick={onRemind}>Remind Rosa</Button>}
            <Button variant={state === "upcoming" ? "secondary" : "primary"} busy={busy === "take"} disabled={med.pills_left < med.dose_amount} onClick={onTake}>Mark as taken</Button>
            <button type="button" className="link min-h-[44px] px-2" onClick={() => setConfirmSkip(true)}>Skip</button>
          </>
        )}
        {open && confirmSkip && (
          <span className="flex flex-wrap items-center gap-2.5" role="group" aria-label={`Skip ${med.name}?`}>
            <span className="font-bold">Skip this dose?</span>
            <Button variant="secondary" onClick={() => setConfirmSkip(false)}>Keep it</Button>
            <Button variant="danger" busy={busy === "skip"} onClick={async () => { await onSkip(); setConfirmSkip(false); }}>Yes, skip</Button>
          </span>
        )}
      </div>
    </li>
  );
}
