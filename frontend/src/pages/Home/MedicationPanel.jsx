import { useState } from "react";
import Button from "../../components/Button";
import StatusBadge from "../../components/StatusBadge";
import StatTile from "../../components/StatTile";
import Notice from "../../components/Notice";
import TextField from "../../components/TextField";
import { api } from "../../api/client";
import { useAppState } from "../../state/AppState";
import { STATUS, daysLeft, runOutDate, statusOf } from "../../lib/inventory";
import { fmtDate, fmtSlot, fmtTime, sameDay } from "../../lib/format";

const METHOD = { voice: "by voice", button: "button", dashboard: "logged by you" };

function recentDoses(med, doses, now) {
  const rows = [];
  for (let back = 0; rows.length < 4 && back < 10; back++) {
    const day = new Date(now); day.setDate(day.getDate() - back);
    for (const slot of [...med.schedule_times].reverse()) {
      const [h, m] = slot.split(":").map(Number);
      const due = new Date(day); due.setHours(h, m, 0, 0);
      if (due > now) continue;
      const d = doses.find((x) => x.medication_id === med.id && x.slot === slot && sameDay(x.taken_at, day));
      const label = med.schedule_times.length > 1 ? `${fmtDate(day)}, ${fmtSlot(slot)}` : fmtDate(day);
      rows.push({ key: `${back}-${slot}`, label, dose: d });
      if (rows.length === 4) break;
    }
  }
  return rows;
}

/** Everything about one medication. Opens in a Dialog from a bottle cap on Home. */
export default function MedicationPanel({ medId, onClose }) {
  const { data, run } = useAppState();
  const med = data.medications.find((m) => m.id === medId);
  const [mode, setMode] = useState(null); // "count" | "edit" | "stop"
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [count, setCount] = useState("");
  const [draft, setDraft] = useState(null);
  const [copied, setCopied] = useState(false);

  if (!med) return <p>This medication is no longer tracked.</p>;

  const now = new Date(data.now);
  const t = data.settings.thresholds;
  const status = statusOf(med, t);
  const s = STATUS[status];
  const days = Math.floor(daysLeft(med));
  const hot = status === "ok" ? "text-ink" : s.text;
  const weekDue = med.doses_per_day * 7;
  const weekAgo = new Date(now.getTime() - 7 * 86_400_000);
  const weekTaken = Math.min(weekDue, data.doses.filter((d) => d.medication_id === med.id && new Date(d.taken_at) > weekAgo).length);
  const todayTaken = data.doses.filter((d) => d.medication_id === med.id && sameDay(d.taken_at, now)).length;

  const act = async (key, fn) => {
    setBusy(key); setError(null);
    try { await run(fn); return true; } catch (e) { setError(e.message); return false; } finally { setBusy(null); }
  };

  const copyDetails = async () => {
    const text = `${med.name} ${med.strength}. ${med.instructions}. Quantity ${med.quantity_start}. Prescriber ${med.prescriber}. Pharmacy ${med.pharmacy_name} ${med.pharmacy_phone}.`;
    try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setError("Couldn't copy. Select the details below instead."); }
  };

  const labelRows = [
    ["Instructions", med.instructions, "instructions"],
    ["Quantity", `${med.quantity_start} tablets`, "quantity_start"],
    [med.otc ? "Bought" : "Filled", med.fill_date ? fmtDate(`${med.fill_date}T12:00`) : "Unknown", "fill_date"],
    ["Refills", med.refills_remaining ?? "Not needed", "refills_remaining"],
    [med.otc ? "Store" : "Pharmacy", [med.pharmacy_name, med.pharmacy_phone].filter(Boolean).join(", "), "pharmacy_name"],
    ["Prescriber", med.prescriber || "None", "prescriber"],
  ];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-4">
          <span aria-hidden="true" className="h-[52px] w-5 flex-none rounded-full" style={{ background: `linear-gradient(180deg, ${s.pill[0]} 50%, ${s.pill[1]} 50%)` }} />
          <div>
            <h2 className="text-[28px] font-bold leading-tight">{med.name} <span className="text-[19px] font-normal text-ink-soft">{med.strength}</span></h2>
            <p className="text-ink-soft">
              {med.dose_amount} tablet{med.doses_per_day > 1 ? `, ${med.doses_per_day} times a day` : ""} at {med.schedule_times.map(fmtSlot).join(" and ")}
              {med.purpose ? `, ${med.purpose}` : ""}
            </p>
          </div>
        </div>
        <div className="flex flex-none items-center gap-2">
          <StatusBadge tone={status}>{s.label}</StatusBadge>
          <button type="button" aria-label="Close" onClick={onClose} className="h-11 w-11 rounded-full bg-track text-2xl font-bold text-navy hover:bg-line-soft">×</button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <StatTile label="Pills left" value={Math.max(0, Math.round(med.pills_left))} tone={hot} />
        <StatTile label="Runs out" value={days <= 0 ? "Now" : fmtDate(runOutDate(med, now))} tone={hot} />
        <StatTile label="Refills left" value={med.refills_remaining ?? "N/A"} tone={med.refills_remaining === 0 ? "text-urgent" : "text-ink"} />
        <StatTile label="This week" value={`${weekTaken} of ${weekDue}`} />
      </div>

      {med.refills_remaining === 0 && (
        <Notice
          tone="urgent"
          title="No refills left"
          actions={
            <>
              {med.prescriber_phone && <Button variant="danger" href={`tel:${med.prescriber_phone.replace(/\D/g, "")}`}>Call {med.prescriber}'s office</Button>}
              <Button variant="secondary" onClick={copyDetails}>{copied ? "Copied" : "Copy prescription details"}</Button>
            </>
          }
        >
          Ask {med.prescriber || "the doctor"} to send a new prescription to {med.pharmacy_name}. This usually takes 1 to 3 days, so ask today.
        </Notice>
      )}
      {med.otc && status !== "ok" && (
        <Notice tone="low" title="Running low">Over the counter, so no prescription needed. Pick some up at any pharmacy this week.</Notice>
      )}

      {error && <p role="alert" className="rounded-2xl bg-urgent-tint px-4 py-3 font-bold text-urgent">{error}</p>}

      {mode === "count" ? (
        <form
          className="flex flex-wrap items-end gap-3 rounded-2xl bg-page p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const n = parseInt(count, 10);
            if (Number.isNaN(n) || n < 0) return setError("Enter how many pills are in the bottle, like 12.");
            if (await act("count", () => api.recordCount(med.id, n))) { setMode(null); setCount(""); }
          }}
        >
          <TextField id="pill-count" label="How many pills are left?" inputMode="numeric" value={count} onChange={(e) => setCount(e.target.value)} autoFocus className="w-48" />
          <Button variant="secondary" onClick={() => setMode(null)}>Cancel</Button>
          <Button type="submit" busy={busy === "count"}>Save count</Button>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2.5">
          <Button busy={busy === "dose"} disabled={med.pills_left < med.dose_amount} onClick={() => act("dose", () => api.logDose(med.id))}>
            {todayTaken >= med.doses_per_day ? "Log an extra dose" : "Log a dose"}
          </Button>
          <Button variant="secondary" onClick={() => setMode("count")}>Correct pill count</Button>
          {status !== "ok" && <Button variant="secondary" busy={busy === "refill"} onClick={() => act("refill", () => api.markRefilled(med.id))}>Mark refill picked up</Button>}
        </div>
      )}

      {mode === "edit" ? (
        <form
          className="grid gap-4 rounded-2xl bg-page p-4 sm:grid-cols-2"
          onSubmit={async (e) => {
            e.preventDefault();
            if (await act("edit", () => api.updateMedication(med.id, { ...draft, quantity_start: Number(draft.quantity_start), refills_remaining: draft.refills_remaining === "" ? null : Number(draft.refills_remaining) }))) setMode(null);
          }}
        >
          <TextField id="e-instr" label="Instructions" value={draft.instructions} onChange={(e) => setDraft({ ...draft, instructions: e.target.value })} className="sm:col-span-2" />
          <TextField id="e-qty" label="Tablets in bottle" inputMode="numeric" value={draft.quantity_start} onChange={(e) => setDraft({ ...draft, quantity_start: e.target.value })} />
          <TextField id="e-ref" label="Refills left" inputMode="numeric" value={draft.refills_remaining ?? ""} onChange={(e) => setDraft({ ...draft, refills_remaining: e.target.value })} />
          <TextField id="e-pres" label="Prescriber" value={draft.prescriber} onChange={(e) => setDraft({ ...draft, prescriber: e.target.value })} />
          <TextField id="e-pharm" label="Pharmacy phone" value={draft.pharmacy_phone} onChange={(e) => setDraft({ ...draft, pharmacy_phone: e.target.value })} />
          <div className="flex justify-end gap-2.5 sm:col-span-2">
            <Button variant="secondary" onClick={() => setMode(null)}>Cancel</Button>
            <Button type="submit" busy={busy === "edit"}>Save details</Button>
          </div>
        </form>
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          <section aria-labelledby="recent-h" className="flex flex-col gap-2.5">
            <h3 id="recent-h" className="text-lg font-bold">Recent doses</h3>
            <ul className="overflow-hidden rounded-2xl border border-line">
              {recentDoses(med, data.doses, now).map((r) => (
                <li key={r.key} className={`flex justify-between gap-3 border-b border-line-soft px-4 py-3 last:border-b-0 ${r.dose ? "" : "bg-low-tint"}`}>
                  <span className="whitespace-nowrap">{r.label}</span>
                  <span className={`text-right font-bold ${r.dose ? "text-ok" : "text-low"}`}>
                    {r.dose ? `Taken ${fmtTime(r.dose.taken_at)}, ${METHOD[r.dose.method] || r.dose.method}` : "Missed"}
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <section aria-labelledby="label-h" className="flex flex-col gap-2.5">
            <h3 id="label-h" className="text-lg font-bold">From the label</h3>
            <dl className="overflow-hidden rounded-2xl border border-line">
              {labelRows.map(([k, v, key]) => {
                const unsure = med.confidence?.[key] === "unsure";
                return (
                  <div key={k} className={`flex justify-between gap-3 border-b border-line-soft px-4 py-3 last:border-b-0 ${unsure ? "bg-low-tint" : ""}`}>
                    <dt className="text-ink-soft">{k}</dt>
                    <dd className="text-right">
                      <span className="font-bold">{v}</span>
                      {unsure && <span className="block text-sm font-bold text-low">Hard to read. Please check.</span>}
                    </dd>
                  </div>
                );
              })}
            </dl>
          </section>
        </div>
      )}

      {mode === "stop" && (
        <Notice
          tone="urgent"
          title={`Stop tracking ${med.name}?`}
          actions={
            <>
              <Button variant="secondary" onClick={() => setMode(null)}>Keep tracking</Button>
              <Button variant="danger" busy={busy === "stop"} onClick={async () => { if (await act("stop", () => api.stopTracking(med.id))) onClose(); }}>Stop tracking</Button>
            </>
          }
        >
          Rosa won't get reminders and you won't get refill texts. Do this only if her doctor stopped it.
        </Notice>
      )}

      <div className="flex flex-wrap justify-between gap-2.5 border-t border-line-soft pt-4">
        <div className="flex flex-wrap gap-2.5">
          <Button variant="secondary" onClick={() => { setDraft({ instructions: med.instructions, quantity_start: med.quantity_start, refills_remaining: med.refills_remaining ?? "", prescriber: med.prescriber, pharmacy_phone: med.pharmacy_phone }); setMode("edit"); }}>Edit details</Button>
          <Button variant="secondary" onClick={() => setMode("stop")}>Stop tracking</Button>
        </div>
        <Button onClick={onClose}>Done</Button>
      </div>
    </div>
  );
}
