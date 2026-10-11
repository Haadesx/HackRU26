import StatusBadge from "../../components/StatusBadge";
import { STATUS, daysLeft, pillCount, runOutDate, statusOf } from "../../lib/inventory";
import { fmtDate, fmtLongDate, plural } from "../../lib/format";

const GLASS = "linear-gradient(90deg, rgba(255,255,255,.7) 0%, rgba(255,255,255,0) 28%, rgba(255,255,255,0) 72%, rgba(255,255,255,.45) 100%)";

/** A prescription bottle whose pill level is the supply. The cap opens the medication. */
export default function PillBottle({ med, now, thresholds, onOpen }) {
  const status = statusOf(med, thresholds);
  const s = STATUS[status];
  const days = Math.floor(daysLeft(med));
  const runs = runOutDate(med, now);
  const count = pillCount(med);
  const [c1, c2] = s.pill;

  return (
    <li className="flex w-[152px] flex-none flex-col items-center">
      <button
        type="button"
        onClick={onOpen}
        aria-label={`${med.name}, ${plural(days, "day")} left, runs out ${fmtLongDate(runs)}, ${s.label}. Open details.`}
        className="h-[38px] w-[152px] cursor-pointer rounded-t-xl rounded-b-md transition-transform hover:-translate-y-0.5 active:translate-y-0.5"
        style={{
          background: "repeating-linear-gradient(90deg, #ffffff 0 7px, #e9eff7 7px 10px)",
          boxShadow: "inset 0 -5px 0 #d8e3f0, 0 2px 0 #cbd9ea",
        }}
      />
      <div aria-hidden="true" className="h-2 w-[134px] bg-[#DFE8F3]" />
      <div
        aria-hidden="true"
        className={`relative h-[214px] w-[140px] overflow-hidden rounded-t-[10px] rounded-b-[24px] ${s.tint}`}
        style={{ backgroundImage: GLASS, boxShadow: "inset 0 0 0 2px rgba(31,58,104,.10)" }}
      >
        <div className="absolute inset-x-2.5 top-[18px] flex h-[62px] flex-col items-center justify-center rounded-lg bg-white px-1 text-center shadow-sm">
          <strong className="text-base leading-tight">{med.name}</strong>
          <span className="text-[13px] text-ink-soft">{med.strength}</span>
        </div>
        <div className="absolute inset-x-2.5 bottom-3 flex flex-wrap-reverse justify-center gap-1">
          {Array.from({ length: count }, (_, i) => (
            <span
              key={i}
              className="h-3 w-6 rounded-full"
              style={{
                background: `linear-gradient(90deg, ${c1} 50%, ${c2} 50%)`,
                boxShadow: "inset 0 2px 0 rgba(255,255,255,.6), 0 0 0 1px rgba(31,58,104,.12)",
              }}
            />
          ))}
        </div>
      </div>
      <strong className={`mt-3.5 h-[34px] text-[26px] leading-[34px] tabular-nums ${s.text}`}>{plural(days, "day")}</strong>
      <span className="h-[26px] leading-[26px]">{fmtDate(runs)}</span>
      <StatusBadge tone={status} className="mt-1.5">{s.label}</StatusBadge>
    </li>
  );
}
