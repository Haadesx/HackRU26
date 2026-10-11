export const FIELDS = [
  { key: "name", label: "Medication name", required: true, why: "Needed to recognize the bottle." },
  { key: "strength", label: "Strength", required: true, placeholder: "10 mg", why: "Needed to tell doses apart." },
  { key: "dose_amount", label: "Tablets per dose", required: true, inputMode: "numeric", why: "Needed to count pills." },
  { key: "schedule_times", label: "Dose times", required: true, placeholder: "08:00, 20:00", why: "Needed to remind Rosa." },
  { key: "quantity_start", label: "Tablets in bottle", required: true, inputMode: "numeric", placeholder: "Check the label, e.g. 30", why: "Needed to warn before Rosa runs out." },
  { key: "refills_remaining", label: "Refills left", inputMode: "numeric", placeholder: "Check the label, e.g. 2", why: "You can also call the pharmacy to check." },
  { key: "pharmacy_name", label: "Pharmacy" },
  { key: "pharmacy_phone", label: "Pharmacy phone", inputMode: "tel" },
  { key: "prescriber", label: "Prescriber", wide: true },
];
export const REQUIRED = FIELDS.filter((f) => f.required).map((f) => f.key);
