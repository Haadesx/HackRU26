/**
 * Dosage-form helpers — tablet vs capsule vs unknown, with noun-aware copy.
 *
 * The hub scan JSON carries additive `dosage_form` / `dose_unit` keys
 * ("tablet" | "capsule" | absent). Unknown never means "tablet": when the
 * label didn't say, the caregiver must choose before the medication can be
 * added, so display copy says "unit(s)" until a form is known.
 */
const ALIASES = {
  tablet: "tablet",
  tablets: "tablet",
  tab: "tablet",
  tabs: "tablet",
  capsule: "capsule",
  capsules: "capsule",
  cap: "capsule",
  caps: "capsule",
};

/** Resolve the form the label reported, preferring `dosage_form` over `dose_unit`. */
export function scanForm(scan) {
  if (!scan || typeof scan !== "object") return null;
  return (
    ALIASES[String(scan.dosage_form || "").trim().toLowerCase()] ||
    ALIASES[String(scan.dose_unit || "").trim().toLowerCase()] ||
    null
  );
}

export function isFormChosen(form) {
  return form === "tablet" || form === "capsule";
}

/** "tablet" | "tablets" | "capsule" | "capsules" | "unit" | "units". */
export function formNoun(form, plural = false) {
  const known = isFormChosen(form) ? form : "unit";
  return plural ? `${known}s` : known;
}

/** Capitalized plural for labels: "Tablets" | "Capsules" | "Units". */
export function formLabel(form) {
  const noun = formNoun(form, true);
  return noun.charAt(0).toUpperCase() + noun.slice(1);
}

/** Capitalized singular for a read-only row: "Tablet" | "Capsule" | "Unit". */
export function formName(form) {
  const noun = formNoun(form, false);
  return noun.charAt(0).toUpperCase() + noun.slice(1);
}
