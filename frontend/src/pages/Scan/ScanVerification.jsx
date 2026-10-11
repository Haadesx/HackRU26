import { useRef, useState } from "react";
import Button from "../../components/Button";
import { api } from "../../api/client";
import { useAppState } from "../../state/AppState";
import { fmtTime } from "../../lib/format";

/**
 * Read-only scan-vs-prescription check from the backend (`scan.verification`).
 *
 * Safety rules: never auto-log, never auto-confirm, no timers. The only write
 * path is the caregiver pressing "Log this dose now", which calls the normal
 * dose endpoint once; the scan itself never records a dose.
 */

const STATUS_VIEW = {
  due_now: {
    icon: "info",
    title: "It's time for a dose",
    role: "status",
    wrap: "bg-mist shadow-[inset_0_0_0_2px_#9CC3EC]",
    fg: "text-navy",
  },
  already_taken: {
    icon: "ok",
    title: "Already logged today",
    role: "status",
    wrap: "bg-ok-tint",
    fg: "text-ok",
  },
  not_due: {
    icon: "info",
    title: "Not due yet",
    role: "status",
    wrap: "bg-mist shadow-[inset_0_0_0_2px_#9CC3EC]",
    fg: "text-navy",
  },
  wrong_medication: {
    icon: "warn",
    title: "Not a medication you're tracking",
    role: "alert",
    wrap: "bg-low-fill",
    fg: "text-low",
  },
  strength_mismatch: {
    icon: "danger",
    title: "Don't take it until a pharmacist checks",
    role: "alert",
    wrap: "bg-urgent-tint",
    fg: "text-urgent",
  },
  uncertain: {
    icon: "neutral",
    title: "We couldn't confirm this bottle",
    role: "status",
    wrap: "bg-track",
    fg: "text-ink-soft",
  },
};

/** One consistent hand-drawn icon family (stroke 2.2, round caps) — never color-only. */
function StatusIcon({ kind }) {
  const common = {
    width: 24,
    height: 24,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  };
  if (kind === "ok") return <svg {...common}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>;
  if (kind === "warn") return <svg {...common}><path d="M12 4l9 16H3z" /><path d="M12 10.5v4" /><path d="M12 17.5h.01" /></svg>;
  if (kind === "danger") return <svg {...common}><path d="M12 3l9 6v6l-9 6-9-6V9z" /><path d="M12 8.5v4" /><path d="M12 16h.01" /></svg>;
  if (kind === "neutral") return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="M9.6 9.2a2.5 2.5 0 1 1 3.4 2.3c-.7.4-1 .9-1 1.7" /><path d="M12 17h.01" /></svg>;
  return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="M12 8.5v4.5" /><path d="M12 16.5h.01" /></svg>;
}

export default function ScanVerification({ verification }) {
  const { refresh } = useAppState();
  const [logging, setLogging] = useState(false);
  const [loggedAt, setLoggedAt] = useState(null);
  const [error, setError] = useState(null);
  const confirmRef = useRef(null);

  const view = STATUS_VIEW[verification.status] || STATUS_VIEW.uncertain;

  const logDose = async () => {
    if (!verification.medication?.id || logging || loggedAt) return;
    setLogging(true);
    setError(null);
    try {
      await api.logDose(verification.medication.id);
      await refresh();
      setLoggedAt(new Date());
      requestAnimationFrame(() => confirmRef.current?.focus());
    } catch (e) {
      setError(e.message || "The hub didn't accept the dose.");
    } finally {
      setLogging(false);
    }
  };

  return (
    <section aria-label="Medication check" role={view.role} className={`rounded-2xl px-5 py-4 ${view.wrap}`}>
      <div className="flex items-start gap-3">
        <span className={`mt-0.5 flex-none ${view.fg}`}>
          <StatusIcon kind={view.icon} />
        </span>
        <div className="flex min-w-0 flex-col gap-2.5">
          <strong className={`text-lg ${view.fg}`}>{view.title}</strong>
          <p className="text-ink">{verification.message}</p>

          {verification.status === "due_now" && verification.can_log && !loggedAt && (
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={logDose} busy={logging}>Log this dose now</Button>
              <span className="text-[15px] text-ink-soft">Only tap after the dose was actually taken.</span>
            </div>
          )}

          {loggedAt && (
            <p ref={confirmRef} tabIndex={-1} role="status" className="font-bold text-ok focus:outline-none">
              Logged at {fmtTime(loggedAt)}. Scanning never records a dose.
            </p>
          )}

          {error && (
            <p role="alert" className="rounded-xl bg-white/70 px-3 py-2 font-bold text-urgent">
              Couldn't log the dose. {error}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
