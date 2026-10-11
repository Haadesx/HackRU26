"""Normalization of drug names and strengths so OCR output, user edits, and OpenFDA data compare equal."""

import re
from decimal import Decimal, InvalidOperation

_UNIT_ALIASES = {
    "mg": "mg",
    "mgs": "mg",
    "milligram": "mg",
    "milligrams": "mg",
    "g": "g",
    "gm": "g",
    "gram": "g",
    "grams": "g",
    "mcg": "mcg",
    "µg": "mcg",
    "μg": "mcg",
    "ug": "mcg",
    "microgram": "mcg",
    "micrograms": "mcg",
    "ml": "mL",
    "iu": "IU",
    "unit": "unit",
    "units": "unit",
    "%": "%",
    "meq": "mEq",
}

_STRENGTH_RE = re.compile(
    r"^\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>[a-zA-Zµμ%]+)?\s*(?:/\s*(?P<per_num>\d+(?:\.\d+)?)?\s*(?P<per_unit>[a-zA-Z]+)?)?\s*$"
)


def _format_number(raw: str) -> str:
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return raw
    normalized = value.normalize()
    text = format(normalized, "f")
    return text


VALID_STRENGTH_RE = re.compile(r"^\d+(?:\.\d+)?\s+\S+$")


def valid_strength(text: str | None) -> bool:
    """True when a normalized strength is a number followed by a unit ("500 mg", "5 mg/mL").

    A label that only shows a bare number, or non-numeric text, is not comparable evidence —
    callers must treat that as unreadable instead of assuming a strength.
    """
    return bool(text) and bool(VALID_STRENGTH_RE.match(str(text).strip()))


def _unit(raw: str | None) -> str | None:
    if not raw:
        return None
    return _UNIT_ALIASES.get(raw.lower(), raw.lower())


def normalize_strength(value) -> str | None:
    """Return "<number> <unit>" (e.g. "500 mg", "5 mg/mL"), or None for empty input.

    Accepts strings ("500mg", "500 MG") or the inference contract shape {"value": 500, "unit": "mg"}.
    OpenFDA's "500 mg/1" (per one unit) collapses to "500 mg".
    """
    if value is None:
        return None
    if isinstance(value, dict):
        num = value.get("value")
        if num is None:
            return None
        unit = value.get("unit") or ""
        value = f"{num} {unit}".strip()
    text = str(value).strip()
    if not text:
        return None
    match = _STRENGTH_RE.match(text)
    if not match:
        return re.sub(r"\s+", " ", text)
    number = _format_number(match.group("num"))
    unit = _unit(match.group("unit"))
    per_num = match.group("per_num")
    per_unit = _unit(match.group("per_unit"))
    result = f"{number} {unit}" if unit else number
    # "500 mg/1" means per one unit (tablet); drop it. Keep real denominators like "/mL" or "/5 mL".
    if per_unit:
        per = f"{_format_number(per_num)} {per_unit}" if per_num and per_num != "1" else per_unit
        result = f"{result}/{per}"
    return result


def normalize_name(name: str | None) -> str:
    if not name:
        return ""
    text = re.sub(r"[^a-z0-9\s-]", " ", name.lower())
    return re.sub(r"\s+", " ", text).strip()


def display_name(name: str) -> str:
    """Clean whitespace for storage; keep the user's capitalization."""
    return re.sub(r"\s+", " ", name).strip()
