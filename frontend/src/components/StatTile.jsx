export default function StatTile({ label, value, tone = "text-ink" }) {
  return (
    <div className="rounded-2xl bg-page px-4 py-3">
      <div className="text-sm text-ink-soft">{label}</div>
      <div className={`text-xl font-bold tabular-nums leading-snug ${tone}`}>{value}</div>
    </div>
  );
}
