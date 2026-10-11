import { fmtTime } from "../../lib/format";

export default function ScanTimeline({ history }) {
  return (
    <ol aria-label="What happened so far" className="grid gap-3 sm:grid-cols-4">
      {history.map((h, i) => {
        const last = i === history.length - 1;
        return (
          <li key={h.step} className={`rounded-2xl px-4 py-3 ${last ? "bg-mist shadow-[inset_0_0_0_2px_#9CC3EC]" : "bg-white border border-line"}`}>
            <strong>{h.step}</strong>
            <div className="text-[15px] text-ink-soft">{fmtTime(h.at)}. {h.detail}</div>
          </li>
        );
      })}
    </ol>
  );
}
