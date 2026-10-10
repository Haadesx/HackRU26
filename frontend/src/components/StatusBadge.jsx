const TONE = {
  ok: "bg-ok-fill text-ok",
  low: "bg-low-fill text-low",
  urgent: "bg-urgent-fill text-urgent",
  info: "bg-mist text-navy",
  grey: "bg-[#ECEFF4] text-ink-soft",
};

export default function StatusBadge({ tone = "info", children, className = "" }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-3 py-1 text-sm font-bold ${TONE[tone]} ${className}`}>
      {children}
    </span>
  );
}
