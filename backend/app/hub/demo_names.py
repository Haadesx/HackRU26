"""Demo mode for the label reader: only these four medicines exist.

When HUB_DEMO_NAMES is on, the medication name on a scan can only ever be one of DEMO_MEDICATIONS.
The name is looked for in everything the OCR read (the whole label, not only the line the reader picked),
so a pharmacy or store name ("University Pharmacy", "Amazon Basic Care") can never become the drug name: if
none of the four is on the label, the name is left unread and the caregiver is asked for another photo.

The strength comes from the same label text, taking a strength printed with mg, mcg or IU (never "303 G" from an
address), preferring one on the line that carries the name. Off by default; the normal reader is unchanged.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.services.normalize import normalize_strength

# (name used everywhere in the app, words that identify it on a label). Long aliases also match OCR noise
# ("Fexofenainein"); short ones must stand alone as a word.
DEMO_MEDICATIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Fluoxetine HCl", ("fluoxetine", "prozac")),
    ("Fexofenadine", ("fexofenadine", "allegra")),
    ("Vitamin D3", ("vitamin d3", "cholecalciferol", "vitamin d", "d3")),
    ("Tylenol", ("tylenol", "acetaminophen", "paracetamol")),
)

EXACT = 0.95   # the alias is printed on the label
FUZZY = 0.90   # the alias is on the label with OCR noise (both are above the "filled" cut-off of 0.85)
FUZZY_MIN = 86  # rapidfuzz partial_ratio for a long alias against the squashed label text

_STRENGTH = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(mg|mcg|µg|ug|iu)\b", re.I)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _score(alias: str, text: str, squashed: str) -> int:
    """100 when printed, the fuzzy score for a long alias read with noise, else 0."""
    if len(alias.replace(" ", "")) <= 3:  # "d3": a word on its own, not part of an Rx number
        return 100 if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text.casefold()) else 0
    a = _squash(alias)
    if a in squashed:
        return 100
    if len(a) >= 6:
        score = fuzz.partial_ratio(a, squashed)
        return int(score) if score >= FUZZY_MIN else 0
    return 0


def find_demo_name(text: str) -> tuple[str, float, str] | None:
    """(canonical name, confidence, alias found) for the best of the four on this label, or None."""
    squashed = _squash(text)
    best: tuple[int, int, str, str] | None = None
    for canonical, aliases in DEMO_MEDICATIONS:
        for alias in aliases:
            score = _score(alias, text, squashed)
            if score and (best is None or (score, len(alias)) > (best[0], best[1])):
                best = (score, len(alias), canonical, alias)
    if best is None:
        return None
    return best[2], (EXACT if best[0] == 100 else FUZZY), best[3]


def _tracked_strength(canonical: str) -> str | None:
    """The strength this demo medicine is tracked with, if it is tracked (needs a hub request)."""
    try:
        from app.hub.state import hub_patient, tracked

        for _hm, item in tracked(hub_patient()):
            if item.medication.name.casefold() == canonical.casefold():
                return normalize_strength(item.medication.strength)
    except Exception:  # noqa: BLE001 - outside a request (tests) there is simply no tracked strength
        return None
    return None


def _label_strengths(text: str) -> list[str]:
    out = []
    for m in _STRENGTH.finditer(text):
        unit = {"µg": "mcg", "ug": "mcg"}.get(m.group(2).lower(), m.group(2))
        if (value := normalize_strength({"value": float(m.group(1)), "unit": unit})) and value not in out:
            out.append(value)
    return out


def _strength_near(text: str, alias: str, tracked: str | None = None) -> str | None:
    """A strength printed on the label. When the label prints the tracked one (Vitamin D3: "25 mcg (1000 IU)"), that
    one; otherwise the one on the line (or the line after) that carries the name. A different strength is still
    returned as printed, so a wrong-strength bottle is still caught."""
    if tracked and tracked in _label_strengths(text):
        return tracked
    lines = [ln for ln in text.splitlines() if ln.strip()]
    key = _squash(alias)[:6]
    order = []
    for i, line in enumerate(lines):
        if key and key in _squash(line):
            order += [i, i + 1, i - 1]
    order += range(len(lines))
    for i in order:
        if 0 <= i < len(lines) and (m := _STRENGTH.search(lines[i])):
            unit = {"µg": "mcg", "ug": "mcg"}.get(m.group(2).lower(), m.group(2))
            return normalize_strength({"value": float(m.group(1)), "unit": unit})
    return None


def apply(readings: dict[str, tuple[str, float]], label_text: str) -> dict[str, tuple[str, float]]:
    """Replace the name (and, when found, the strength) with demo-safe readings. Never returns another name."""
    out = dict(readings)
    out.pop("name", None)
    hit = find_demo_name(label_text + "\n" + (readings.get("name", ("", 0.0))[0] or ""))
    if hit is None:
        return out
    canonical, confidence, alias = hit
    out["name"] = (canonical, confidence)
    strength = _strength_near(label_text, alias, _tracked_strength(canonical))
    if strength:
        out["strength"] = (strength, max(out.get("strength", ("", 0.0))[1], 0.9))
    return out
