export default function SectionHeader({ title, hint, id, action, level = 2 }) {
  const H = `h${level}`;
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div>
        <H id={id} className="text-xl font-bold text-ink">{title}</H>
        {hint && <p className="text-ink-soft">{hint}</p>}
      </div>
      {action}
    </div>
  );
}
