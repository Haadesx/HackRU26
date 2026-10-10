import StatusBadge from "../../components/StatusBadge";
import EmptyState from "../../components/EmptyState";
import { relativeDay } from "../../lib/format";

const LABEL = {
  no_refills: ["New prescription needed", "urgent"],
  low_3: ["Refill now", "urgent"],
  low_5: ["Refill soon", "low"],
  low_7: ["Refill soon", "low"],
};

export default function AlertFeed({ alerts, now }) {
  return (
    <section aria-labelledby="alerts-h" className="flex flex-col gap-3">
      <h2 id="alerts-h" className="text-xl font-bold">Texts sent to you</h2>
      {alerts.length === 0 ? (
        <EmptyState>No texts yet. You'll get one when any medication drops below a week's supply.</EmptyState>
      ) : (
        <ul className="flex flex-col gap-2.5">
          {alerts.slice(0, 5).map((a) => {
            const [label, tone] = LABEL[a.type] || ["Alert", "info"];
            return (
              <li key={a.id} className="card flex flex-col items-start gap-1 p-4">
                <StatusBadge tone={tone}>{label}</StatusBadge>
                <span>{a.message}</span>
                <span className="text-sm text-ink-soft">{relativeDay(a.sent_at, now)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
