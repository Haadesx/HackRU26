export default function EmptyState({ children, action }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-line p-6 text-center text-ink-soft">
      <p>{children}</p>
      {action}
    </div>
  );
}
