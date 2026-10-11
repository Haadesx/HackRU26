import StatusBadge from "../../components/StatusBadge";
import { relativeDay } from "../../lib/format";

const LABEL = { wrong_bottle: "Wrong bottle", double_dose: "Double dose", skipped: "Skipped dose", missed: "Missed dose" };

export default function MistakesCaught({ events, now }) {
  if (!events.length) return null;
  return (
    <section aria-labelledby="caught-h" className="flex flex-col gap-3">
      <h2 id="caught-h" className="text-xl font-bold">Mistakes caught</h2>
      <ul className="flex flex-col gap-2.5">
        {events.map((e) => (
          <li key={e.id} className="card flex flex-col items-start gap-1 p-4">
            <StatusBadge tone="info">{LABEL[e.type] || "Heads up"}</StatusBadge>
            <span>{e.message}</span>
            <span className="text-sm text-ink-soft">{relativeDay(e.at, now)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
