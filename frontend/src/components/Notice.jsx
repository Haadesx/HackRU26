const TONE = {
  urgent: ["bg-urgent-tint", "text-urgent"],
  low: ["bg-low-tint", "text-low"],
  ok: ["bg-ok-tint", "text-ok"],
  info: ["bg-mist", "text-navy"],
};

export default function Notice({ tone = "info", title, children, actions, className = "" }) {
  const [bg, fg] = TONE[tone];
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 rounded-2xl px-5 py-4 ${bg} ${className}`} role={tone === "urgent" ? "alert" : undefined}>
      <div className="min-w-0">
        {title && <strong className={`block text-lg ${fg}`}>{title}</strong>}
        {children && <div className="text-ink">{children}</div>}
      </div>
      {actions && <div className="flex flex-wrap gap-3">{actions}</div>}
    </div>
  );
}
