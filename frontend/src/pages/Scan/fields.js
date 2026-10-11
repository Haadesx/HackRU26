import { formLabel } from "../../lib/dosageForm";

export const FIELDS = [
  { key: "name", label: "Medication name", required: true, why: "Needed to recognize the bottle." },
  { key: "strength", label: "Strength", required: true, placeholder: "10 mg", why: "Needed to tell doses apart." },
  { key: "dose_amount", label: "Units per dose", required: true, inputMode: "numeric", why: "Needed to count doses." },
  { key: "schedule_times", label: "Dose times", required: true, placeholder: "08:00, 20:00", why: "Needed to remind Rosa." },
  { key: "quantity_start", label: "Units in bottle", required: true, inputMode: "numeric", placeholder: "Check the label, e.g. 30", why: "Needed to warn before Rosa runs out." },
  { key: "refills_remaining", label: "Refills left", inputMode: "numeric", placeholder: "Check the label, e.g. 2", why: "You can also call the pharmacy to check." },
  { key: "pharmacy_name", label: "Pharmacy" },
  { key: "pharmacy_phone", label: "Pharmacy phone", inputMode: "tel" },
  { key: "prescriber", label: "Prescriber", wide: true },
];
export const REQUIRED = FIELDS.filter((f) => f.required).map((f) => f.key);

/** Form-aware label for countable fields; other fields keep their static label. */
export function fieldLabel(field, form) {
  if (field.key === "dose_amount") return `${formLabel(form)} per dose`;
  if (field.key === "quantity_start") return `${formLabel(form)} in bottle`;
  return field.label;
}
