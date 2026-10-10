/** Capsule switch. Renders a real checkbox so it works with keyboards and screen readers. */
export default function Toggle({ label, checked, onChange }) {
  return (
    <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-4">
      <span>{label}</span>
      <span className="relative inline-flex flex-none">
        <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span className="h-[30px] w-[52px] rounded-full bg-line-soft transition-colors peer-checked:bg-gradient-to-r peer-checked:from-sky peer-checked:to-ice peer-focus-visible:outline peer-focus-visible:outline-[3px] peer-focus-visible:outline-offset-2 peer-focus-visible:outline-navy" />
        <span className="absolute left-[3px] top-[3px] h-6 w-6 rounded-full bg-white shadow transition-transform peer-checked:translate-x-[22px]" />
      </span>
    </label>
  );
}
