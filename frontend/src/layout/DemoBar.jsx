import { useState } from "react";
import { api } from "../api/client";
import { useAppState } from "../state/AppState";
import { fmtDate } from "../lib/format";

/** Presenter controls. Only shown when running on mock data. */
export default function DemoBar() {
  const { data, run } = useAppState();
  const [busy, setBusy] = useState(false);
  const go = (fn) => async () => {
    setBusy(true);
    try { await run(fn); } finally { setBusy(false); }
  };
  return (
    <div role="region" aria-label="Demo controls" className="fixed inset-x-0 bottom-0 z-40 bg-navy text-mist">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6 lg:px-8 xl:px-10 2xl:px-12">
        <span>Demo mode. Today is <strong aria-live="polite">{fmtDate(data.now)}</strong></span>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="pill pill-secondary" disabled={busy} onClick={go(() => api.advanceDays(1))}>Skip 1 day</button>
          <button type="button" className="pill pill-secondary" disabled={busy} onClick={go(() => api.advanceDays(7))}>Skip a week</button>
          <button type="button" disabled={busy} onClick={go(api.reset)} className="inline-flex min-h-[44px] items-center rounded-full border-2 border-mist px-5 font-bold">
            Reset demo
          </button>
        </div>
      </div>
    </div>
  );
}
