const STEPS = ["Scan the label", "Check the details", "Add to schedule"];

export default function ScanSteps({ current }) {
  return (
    <ol aria-label="Steps" className="flex flex-wrap gap-2">
      {STEPS.map((s, i) => (
        <li key={s} aria-current={i === current ? "step" : undefined}
          className={`rounded-full px-4 py-2 ${i === current ? "bg-gradient-to-r from-sky to-ice font-bold text-navy" : i < current ? "bg-ok-fill text-ok" : "bg-track text-ink-soft"}`}>
          {i + 1}. {s}
        </li>
      ))}
    </ol>
  );
}
