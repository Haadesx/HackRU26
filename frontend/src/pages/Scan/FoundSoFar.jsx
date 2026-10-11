import Button from "../../components/Button";
import StatusBadge from "../../components/StatusBadge";
import { FIELDS } from "./fields";
import { formLabel, scanForm } from "../../lib/dosageForm";

const SHORT = { name: "Name", strength: "Strength", schedule_times: "Dose times",
  refills_remaining: "Refills left", pharmacy_name: "Pharmacy",
  pharmacy_phone: "Pharmacy phone", prescriber: "Prescriber" };

export default function FoundSoFar({ scan }) {
  const fields = scan?.fields;
  const form = scanForm(scan);
  const labels = {
    ...SHORT,
    dose_amount: `${formLabel(form)} per dose`,
    quantity_start: `${formLabel(form)} in bottle`,
  };
  const missing = fields ? FIELDS.filter((f) => fields[f.key].state === "missing").length : 0;
  return (
    <section aria-labelledby="found-h" className="card flex flex-col gap-2.5 p-5">
      <h2 id="found-h" className="text-xl font-bold">Found so far</h2>
      {!fields ? (
        <p className="text-ink-soft">Take a photo and MedCheck will read the label here.</p>
      ) : (
        <>
          <ul className="flex flex-col gap-2" aria-live="polite">
            {FIELDS.map((f) => {
              const v = fields[f.key];
              return (
                <li key={f.key} className="flex items-center justify-between gap-3">
                  <span>{labels[f.key]}</span>
                  {v.state === "filled" && <StatusBadge tone="ok">{v.value}</StatusBadge>}
                  {v.state === "unsure" && (
                    // Show what was read; the tag (and the Verify step) asks the caregiver to confirm it.
                    <StatusBadge tone="low" className="min-w-0 max-w-[65%]">
                      <span className="truncate">{v.value || "Unclear"}</span>
                      <span className="ml-1 shrink-0 font-normal">· check</span>
                    </StatusBadge>
                  )}
                  {v.state === "missing" && <StatusBadge tone="urgent">Not found yet</StatusBadge>}
                </li>
              );
            })}
          </ul>
          {missing > 0 && <p className="text-[15px] text-ink-soft">Turn the bottle and take another photo. The quantity is often on the back of the label.</p>}
          <Button to={`/scan/${scan.id}/verify`} className="mt-1">Check the details</Button>
          <span className="text-center text-sm text-ink-soft">You can fill in anything missing on the next step.</span>
        </>
      )}
    </section>
  );
}
