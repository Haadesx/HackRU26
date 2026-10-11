import { useEffect, useRef } from "react";

/**
 * Modal built on the native <dialog>: Esc closes it, focus stays inside,
 * and the browser returns focus to whatever opened it.
 */
export default function Dialog({ open, onClose, label, children, className = "max-w-3xl" }) {
  const ref = useRef(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={label}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className={`w-[calc(100%-2rem)] ${className} rounded-[22px] bg-white p-0 text-ink shadow-dialog backdrop:bg-ink/45`}
    >
      {open && <div className="max-h-[85vh] overflow-y-auto overscroll-contain p-6 sm:p-7">{children}</div>}
    </dialog>
  );
}
