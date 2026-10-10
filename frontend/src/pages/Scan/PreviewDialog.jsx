import Dialog from "../../components/Dialog";
import Button from "../../components/Button";
import StatusBadge from "../../components/StatusBadge";
import { fmtSlot } from "../../lib/format";

/** Read-only check before saving. Edit closes it; Add sends the data once. */
export default function PreviewDialog({ open, values, changed, onEdit, onAdd, adding, error }) {
  const times = String(values.schedule_times || "").split(",").map((t) => t.trim()).filter(Boolean);
  const perDay = times.length * (Number(values.dose_amount) || 1);
  const days = perDay ? Math.floor(Number(values.quantity_start) / perDay) : 0;
  const tag = (k) => changed[k] && <StatusBadge tone="info">{changed[k] === "added" ? "Added by you" : "Corrected by you"}</StatusBadge>;
  const rows = [
    ["Tablets in bottle", values.quantity_start, "quantity_start"],
    ["Refills left", values.refills_remaining || "None", "refills_remaining"],
    ["Prescriber", values.prescriber || "None", "prescriber"],
    ["Pharmacy", [values.pharmacy_name, values.pharmacy_phone].filter(Boolean).join(", ") || "None", "pharmacy_name"],
    ["Supply", `About ${days} days`, null],
  ];

  return (
    <Dialog open={open} onClose={onEdit} label={`Check ${values.name} before adding`} className="max-w-2xl">
      <div className="flex flex-col gap-5">
        <div>
          <h2 className="text-[28px] font-bold leading-tight">Check {values.name} before adding</h2>
          <p className="text-ink-soft">This is what MedCheck will save. Details you typed in are marked.</p>
        </div>
        <div className="flex items-center gap-4 rounded-2xl bg-mist px-5 py-4">
          <span aria-hidden="true" className="h-11 w-[18px] flex-none rounded-full bg-gradient-to-b from-sky to-ice" />
          <div><strong className="text-[22px]">{values.name} {values.strength}</strong><div>{values.dose_amount || 1} tablet at {times.map(fmtSlot).join(" and ")}</div></div>
        </div>
        <dl>
          {rows.map(([k, v, key]) => (
            <div key={k} className="flex justify-between gap-4 border-b border-line-soft py-3 last:border-b-0">
              <dt className="text-ink-soft">{k}</dt>
              <dd className="flex flex-wrap items-center justify-end gap-2.5"><strong>{v}</strong>{key && tag(key)}</dd>
            </div>
          ))}
        </dl>
        <div className="rounded-2xl bg-ok-tint px-5 py-4">
          <strong>After you add it</strong>
          <p>Rosa gets her first reminder at {fmtSlot(times[0] || "08:00")}. You'll get a text when about a week of tablets is left.</p>
        </div>
        {error && <p role="alert" className="rounded-2xl bg-urgent-tint px-4 py-3 font-bold text-urgent">Couldn't add {values.name}. {error} Your details are kept, so try again.</p>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button variant="secondary" size="lg" onClick={onEdit} disabled={adding}>Edit</Button>
          <Button size="lg" onClick={onAdd} busy={adding}>{error ? "Try again" : "Add"}</Button>
        </div>
      </div>
    </Dialog>
  );
}
