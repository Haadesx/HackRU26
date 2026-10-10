"""Structured extraction from label text (MedCheck PI-2 / Orion).

Safety invariants (AGENTS.md §6):

* ``raw_text`` is preserved verbatim; structured values are built from source
  substrings and keep ``confidence`` + ``source``.
* Drug names are never fabricated. A canonical name is emitted only when a
  source token matches the standard-name lexicon (with OCR-noise correction);
  otherwise the verbatim source token is returned with low confidence.
* **Strength** (mass/concentration, e.g. ``500 mg``) is kept strictly separate
  from **quantity per dose** (count of dosage forms, e.g. ``Take 2 tablets``).
* Instruction items are verbatim substrings of the source text.

Public API::

    extract_fields(raw_text, hints=None) -> Extraction
    parse_instructions(raw_text) -> list[InstructionItem]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .lexicon import (
    CONFUSABLE_DIGITS,
    DRUG_NAMES,
    FORM_CANONICAL,
    SALT_SUFFIXES,
    normalize_form,
    normalize_unit,
    match_drug_name,
)
from .types import (
    LABEL_META_KEYS,
    Extraction,
    FieldString,
    FieldStrength,
    InstructionItem,
    absent_strength,
    absent_string,
    has_readable_content,
)

# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #

# No leading word boundary: OCR often glues strength to the name/form
# ("LEVOTHYROXINE100MCG", "CALCIUM2OMG").
STRENGTH_RE = re.compile(
    # Allowed to start at a word boundary, or mid-token only when the next
    # character is a digit (blocks "IL10" in "LISINOPRIL10"/"ssiu" in
    # "Potassium", keeps "100MCG" and "2OMG" glued forms).
    r"(?:(?<![A-Za-z])|(?=\d))"
    r"(?P<num>[0-9OoIlSsBbZzGgQq]{1,5}(?:[.,][0-9OoIlSsBbZzGg]{1,3})?)"
    r"\s*"
    r"(?P<unit>milligrams?|micrograms?|millilit(?:er|re)s?|grams?|mg|mcg|ug|µg|g|ml|iu|units?|%)"
    r"(?!\d)",
    re.IGNORECASE,
)

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")

_FORM_ALTERNATION = "|".join(sorted(FORM_CANONICAL, key=len, reverse=True))

FORM_RE = re.compile(
    r"(?<![A-Za-z])(" + _FORM_ALTERNATION + r")",
    re.IGNORECASE,
)

FORM_LOOSE_RE = re.compile("(" + _FORM_ALTERNATION + r")", re.IGNORECASE)

DOSE_RE = re.compile(
    r"(?:(?<![A-Za-z])take\s*)?"
    r"(?P<qty>\d+(?:\.\d+)?(?:\s*(?:-|to)\s*\d+(?:\.\d+)?)?)\s*"
    r"(?P<form>dropperfuls?|teaspoons?|tablespoons?|capsules?|caplets?|caps?|tablets?|tabs?|softgels?|"
    r"suppositor(?:y|ies)|sachets?|packets?|patches?|sprays?|puffs?|drops?|geltabs?|pills?|"
    r"tsp|tbsp|units?|ml)",
    re.IGNORECASE,
)

FREQ_RE = re.compile(
    r"(?:once|twice|thrice)(?:\s*(?:daily|a\s*day|per\s*day|a\s*week|per\s*week|a\s*month|per\s*month))?"
    r"|(?:three|four|\d+)\s*times(?:\s*(?:a|per|each)\s*(?:day|week|month))?"
    r"|\d+\s*x(?:\s*(?:a|per)\s*day)?"
    r"|every\s*(?:\d+(?:\s*(?:to|-)\s*\d+)?\s*)?(?:hours?|hrs?|days?|weeks?|months?|"
    r"mornings?|evenings?|nights?|other\s*day)"
    r"|daily|weekly|monthly|nightly|at\s*bedtime|bedtime"
    r"|in\s*the\s*(?:morning|afternoon|evening|night)|at\s*night"
    r"|q\.?\d+\s*h|qid|tid|bid|qd|qhs|qam|qpm|prn|as\s*needed|as\s*directed|per\s*day|a\s*day",
    re.IGNORECASE,
)

ROUTE_RE = re.compile(
    r"(?:by\s*mouth|orally|oral|p\.?o\.?|sublingual(?:ly)?|under\s*the\s*tongue|topical(?:ly)?|"
    r"apply|inhale[dr]?|inhalation|nasal(?:ly)?|ophthalmic|otic|rectal(?:ly)?|vaginal(?:ly)?|"
    r"intravenous(?:ly)?|i\.?v\.?|i\.?m\.?|injection|transdermal)",
    re.IGNORECASE,
)

DURATION_RE = re.compile(
    r"(?:for\s*(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fourteen|thirty)\s*"
    r"(?:days?|weeks?|months?)|x\s*\d+\s*(?:days?|weeks?|months?)|until\s*(?:finished|gone)"
    r"|short\s*[- ]?term)",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Structured per-dose quantity (contract v1.1: instructions.dose)
# --------------------------------------------------------------------------- #

# Dosage-form words accepted right after a quantity (lowercase singular output).
_DOSE_FORM_PATTERN = (
    r"dropperfuls?|teaspoons?|tablespoons?|capsules?|caplets?|caps?|tablets?|tabs?|softgels?|"
    r"suppositor(?:y|ies)|sachets?|packets?|patches?|sprays?|puffs?|drops?|geltabs?|pills?|"
    r"tsp|tbsp|units?|ml"
)

# Canonical dose unit: form words plus countable volumes/units.
DOSE_UNIT_CANONICAL: dict[str, str] = {
    **FORM_CANONICAL,
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "millilitres": "ml",
    "tsp": "tsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tbsp": "tbsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "dropperful": "dropperful",
    "dropperfuls": "dropperful",
    "puff": "puff",
    "puffs": "puff",
    "packet": "packet",
    "packets": "packet",
    "unit": "unit",
    "units": "unit",
}

_QUANTITY_WORDS: dict[str, float] = {
    "half": 0.5,
    "quarter": 0.25,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
}

_UNICODE_FRACTIONS: dict[str, float] = {"½": 0.5, "¼": 0.25, "¾": 0.75}

_ARTICLE = r"(?:a\s+|an\s+|of\s+a\s+)?"

_WORD_DOSE_RE = re.compile(
    r"\b(?P<qty>" + "|".join(_QUANTITY_WORDS) + r")(?P<extra>\s+and\s+a\s+half)?\s*"
    r"" + _ARTICLE + r"(?P<form>" + _DOSE_FORM_PATTERN + r")\b",
    re.IGNORECASE,
)

_FRACTION_DOSE_RE = re.compile(
    r"(?<![\d/])(?:(?P<whole>\d+)\s+)?(?P<num>\d{1,2})\s*/\s*(?P<den>\d{1,2})\s*"
    r"" + _ARTICLE + r"(?P<form>" + _DOSE_FORM_PATTERN + r")\b",
    re.IGNORECASE,
)

_UNICODE_DOSE_RE = re.compile(
    r"(?P<frac>[½¼¾])\s*" + _ARTICLE + r"(?P<form>" + _DOSE_FORM_PATTERN + r")\b",
    re.IGNORECASE,
)

# A range such as "1 to 2" or "1-2" is ambiguous for the backend quantity.
_DOSE_RANGE_RE = re.compile(
    r"(?:\d+(?:\.\d+)?|\d+\s*/\s*\d+)\s*(?:to|-)\s*(?:\d+(?:\.\d+)?|\d+\s*/\s*\d+)",
    re.IGNORECASE,
)

_DOSE_FORM_SEARCH_RE = re.compile(_DOSE_FORM_PATTERN, re.IGNORECASE)

WARNING_RE = re.compile(
    r"\b(?:warning|caution|do\s*not|don'?t|avoid|alcohol|grapefruit|drowsi\w*|sleepy|driv\w*|"
    r"machinery|pregnan\w*|breast[- ]?feed\w*|nursing|allerg\w*|side\s*effects?|stop\s*(?:taking|use)|"
    r"consult|physician|doctor|pharmacist|keep\s*out\s*of\s*reach|children|kidney|liver|may\s*cause|"
    r"dizz\w*|sunlight|crush|chew|swallow\s*whole|exceed|overdose|emergency|call\s*your)\b",
    re.IGNORECASE,
)

MANUFACTURER_RE = re.compile(
    r"(?:mfr|manufactured\s+by|distributed\s+by|dist\.?\s+by)\s*[:\-]?\s*"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9 .,&'\-]{1,60})",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Pharmacy-label metadata (contract v1.3 label_meta)
# --------------------------------------------------------------------------- #

QUANTITY_RE = re.compile(r"\b(?:QTY|QUANTITY)\s*[:#.]?\s*(?P<value>\d{1,4})(?![\dA-Za-z])", re.IGNORECASE)
REFILLS_RE = re.compile(r"\bREFILLS?\s*[:#.]?\s*(?P<value>\d{1,3})(?![\dA-Za-z])", re.IGNORECASE)
NO_REFILLS_RE = re.compile(r"\bno\s+refills?\b", re.IGNORECASE)
PHARMACY_LABEL_RE = re.compile(r"\bPharmacy\s*[:\-]\s*(?P<value>[^\n]+)", re.IGNORECASE)
PHARMACY_WORD_RE = re.compile(r"pharmacy", re.IGNORECASE)
PHONE_LABEL_RE = re.compile(r"\b(?:Tel|Phone|Ph)\s*[:.]?\s*(?P<value>\+?[\d(][\d\s().\-]{6,})", re.IGNORECASE)
PHONE_GENERIC_RE = re.compile(
    r"(?P<value>\(\d{3}\)\s*\d{3}[-.\s]\d{4}|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b)"
)
PRESCRIBER_RE = re.compile(r"\bPrescriber\s*[:.]?\s*(?P<value>[^\n]+)", re.IGNORECASE)
PRESCRIBER_DR_RE = re.compile(
    r"\b(?P<value>(?:Dr|Doctor)\.?\s+[A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4})"
)

# Schedule derivation: once/twice/three-times/bedtime only; anything else -> None.
_SCHEDULE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:three\s*times|thrice|tid|t\.i\.d\.?)\b", re.IGNORECASE), "08:00, 14:00, 20:00"),
    (re.compile(r"\b(?:twice|bid|b\.i\.d\.?)\b", re.IGNORECASE), "08:00, 20:00"),
    (re.compile(r"\b(?:once|every\s*day|daily|qd|q\.d\.?|q24h)\b", re.IGNORECASE), "08:00"),
    (re.compile(r"\b(?:at\s*bedtime|bedtime|nightly|qhs|q\.h\.s\.?)\b", re.IGNORECASE), "20:00"),
)
SCHEDULE_BASE_CONFIDENCE = 0.9
SCHEDULE_DERIVATION_FACTOR = 0.8

# Cadences the simple four-way mapping does not cover: leave schedule_times None.
_SCHEDULE_UNSUPPORTED_RE = re.compile(
    r"\b(?:weekly|monthly|every\s*(?:\d+|other)\s*(?:hours?|hrs?|days?|weeks?)|every\s*other\s*day|"
    r"as\s*needed|prn|q\.?\d+\s*h)\b",
    re.IGNORECASE,
)

# Words that must never be mistaken for a drug name in the fallback path.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "take",
        "use",
        "do",
        "not",
        "warning",
        "caution",
        "each",
        "contains",
        "ndc",
        "rx",
        "only",
        "store",
        "keep",
        "out",
        "reach",
        "children",
        "mfr",
        "exp",
        "lot",
        "dose",
        "daily",
        "mouth",
        "oral",
        "by",
        "for",
        "with",
        "food",
        "water",
        "doctor",
        "pharmacist",
        "once",
        "twice",
        "film",
        "coated",
        "delayed",
        "release",
        "extended",
        "immediate",
        "tablets",
        "capsules",
        "usp",
        "mg",
        "mcg",
        "ml",
    }
)

_WARNING_KIND = "warning"
_KIND_ORDER = {"dose": 0, "frequency": 1, "route": 2, "duration": 3}


# --------------------------------------------------------------------------- #
# Numeric helpers
# --------------------------------------------------------------------------- #


def _parse_number_token(token: str) -> tuple[float | None, bool]:
    """Parse a numeric token, correcting predictable OCR digit confusions.

    Returns ``(value, had_confusables)``. ``"5O0" -> (500.0, True)``.
    """
    token = token.strip()
    if not token:
        return None, False
    mapped = "".join(CONFUSABLE_DIGITS.get(ch, ch) for ch in token)
    for candidate, had_confusables in ((token, False), (mapped, mapped != token)):
        text = candidate.replace(" ", "")
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+", text):
            text = text.replace(",", "")
        elif re.fullmatch(r"\d+,\d+", text):
            text = text.replace(",", ".")
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            try:
                value = float(text)
            except ValueError:  # pragma: no cover - defensive
                continue
            if value > 0:
                return value, had_confusables
    return None, False


def _line_index(text: str, position: int) -> int:
    return text.count("\n", 0, position)


def _line_text(text: str, line_index: int) -> str:
    lines = text.split("\n")
    if 0 <= line_index < len(lines):
        return lines[line_index]
    return ""


# --------------------------------------------------------------------------- #
# Strength
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StrengthMatch:
    raw: str
    value: float
    unit: str
    start: int
    end: int
    line_index: int
    had_confusables: bool


def find_strengths(text: str) -> list[StrengthMatch]:
    """Find mass/concentration values such as ``500 mg`` or ``100MCG``.

    Quantity-per-dose counts (``2 tablets``) are excluded by construction: the
    unit must be a mass/concentration unit, never a dosage form.
    """
    matches: list[StrengthMatch] = []
    for match in STRENGTH_RE.finditer(text):
        numeric = match.group("num")
        if not any(ch.isdigit() for ch in numeric) and len(numeric) < 2:
            continue  # lone "O"/"l" is more likely a letter than a number
        value, had_confusables = _parse_number_token(numeric)
        if value is None:
            continue
        unit = normalize_unit(match.group("unit"))
        if unit is None:
            continue
        line = _line_index(text, match.start())
        if unit == "%" and WARNING_RE.search(_line_text(text, line)):
            continue  # e.g. "contains 5% alcohol" is a warning, not the strength
        matches.append(
            StrengthMatch(
                raw=match.group(0).strip(),
                value=value,
                unit=unit,
                start=match.start(),
                end=match.end(),
                line_index=line,
                had_confusables=had_confusables,
            )
        )
    return matches


def _select_strength(
    matches: list[StrengthMatch],
    name_line: int | None,
    hints: dict[str, Any],
) -> FieldStrength:
    if not matches:
        return absent_strength()

    hint_value = hints.get("strength_value")
    hint_unit = normalize_unit(hints.get("strength_unit"))

    def score(match: StrengthMatch) -> tuple:
        same_line = 1 if name_line is not None and match.line_index == name_line else 0
        hinted = 1 if hint_value is not None and match.value == hint_value and match.unit == hint_unit else 0
        non_percent = 1 if match.unit != "%" else 0
        proximity = -abs(match.line_index - (name_line if name_line is not None else 0))
        return (non_percent, same_line, hinted, proximity, -match.start)

    best = max(matches, key=score)
    same_line = name_line is not None and best.line_index == name_line
    confidence = 0.9 if same_line else 0.75
    if best.had_confusables:
        confidence *= 0.85
    if best.unit == "%":
        confidence *= 0.8
    return FieldStrength(
        value=best.value,
        unit=best.unit,
        confidence=round(confidence, 4),
        source="ocr",
        raw=best.raw,
    )


# --------------------------------------------------------------------------- #
# Name / form / manufacturer
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class NameMatch:
    raw: str
    value: str
    start: int
    end: int
    line_index: int
    distance: int | None  # None -> verbatim fallback (no lexicon match)
    normalized: bool


def _strip_trailing_noise(tokens: list[str]) -> list[str]:
    while tokens:
        tail = tokens[-1].casefold()
        if tail in SALT_SUFFIXES or normalize_form(tail) is not None or tail in _STOPWORDS:
            tokens = tokens[:-1]
            continue
        if tail in {"film-coated", "delayed-release", "extended-release", "immediate-release"}:
            tokens = tokens[:-1]
            continue
        break
    return tokens


def _iter_token_windows(line: str, line_offset: int):
    tokens = [(m.group(0), line_offset + m.start(), line_offset + m.end()) for m in TOKEN_RE.finditer(line)]
    for size in (3, 2, 1):
        if size > len(tokens):
            continue
        for start in range(0, len(tokens) - size + 1):
            window = tokens[start : start + size]
            stripped = _strip_trailing_noise([t[0] for t in window])
            if not stripped:
                continue
            kept = window[: len(stripped)]
            joined = "".join(stripped)
            yield kept, joined


def find_name(
    text: str,
    extra_names: Iterable[str] = (),
    name_hint: str | None = None,
) -> NameMatch | None:
    """Find the medication name token span, tolerating OCR noise.

    A name is emitted only from source-token spans. The lexicon corrects
    predictable confusions (``Metform1n``); when nothing matches, the verbatim
    token is returned as a low-confidence fallback rather than inventing a name.
    """
    strength_lines = {m.line_index for m in find_strengths(text)}
    hint_norm = name_hint.casefold() if name_hint else None
    candidates: list[tuple[tuple, NameMatch]] = []

    lines = text.split("\n")
    offset = 0
    for line_index, line in enumerate(lines):
        for kept, joined in _iter_token_windows(line, offset):
            raws = [t[0] for t in kept]
            raw_span = " ".join(raws)
            matched = match_drug_name(joined, extra_names)
            if matched is None and len(raws) > 1:
                matched = match_drug_name(raws[0], extra_names)
                if matched is not None and len(raws) > 1:
                    kept = kept[:1]
                    raw_span = raws[0]
            if matched is None:
                continue
            canonical, distance = matched
            if hint_norm and canonical.casefold() == hint_norm:
                distance = max(0, distance - 1)
            start, end = kept[0][1], kept[-1][2]
            on_strength_line = 0 if line_index in strength_lines else 1
            order = (distance, on_strength_line, line_index, -len(kept), start)
            candidates.append(
                (order, NameMatch(raw=raw_span, value=canonical, start=start, end=end,
                                  line_index=line_index, distance=distance, normalized=True))
            )
        offset += len(line) + 1

    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    # Fallback: first plausible source token in the label header (verbatim value).
    offset = 0
    for line_index, line in enumerate(lines[:3]):
        for token_match in TOKEN_RE.finditer(line):
            token = token_match.group(0)
            folded = token.casefold()
            if len(token) < 4 or folded in _STOPWORDS or folded in SALT_SUFFIXES:
                continue
            if normalize_form(token) is not None:
                continue
            if sum(ch.isalpha() for ch in token) < 2:
                continue
            return NameMatch(
                raw=token,
                value=token,
                start=offset + token_match.start(),
                end=offset + token_match.end(),
                line_index=line_index,
                distance=None,
                normalized=False,
            )
        offset += len(line) + 1
    return None


def _name_confidence(match: NameMatch, name_hint: str | None) -> float:
    if match.distance is None:
        return 0.3
    if match.distance == 0:
        confidence = 0.95
    elif match.distance == 1:
        confidence = 0.8
    else:
        confidence = 0.65
    if name_hint and match.value.casefold() == name_hint.casefold():
        confidence = min(0.98, confidence + 0.03)
    return round(confidence, 4)


def _form_merge_allowed(text: str, match: re.Match) -> bool:
    """Allow forms glued to neighboring words by OCR (``gTablets``, ``COATEDTABLE``)."""
    previous = text[match.start() - 1] if match.start() else ""
    if not previous.isalpha():
        return True
    first = match.group(0)[0]
    if previous.islower() and first.isupper():
        return True
    # Uppercase run split mid-word (e.g. "COATEDTABLE"); only accept longer forms.
    return len(match.group(0)) >= 5


def find_form(text: str, name: NameMatch | None = None, strengths: list[StrengthMatch] | None = None) -> FieldString:
    """Find the dosage form (tablet/capsule/solution/...), nearest to name/strength."""
    matches = list(FORM_RE.finditer(text))
    if not matches:
        matches = [m for m in FORM_LOOSE_RE.finditer(text) if _form_merge_allowed(text, m)]
    if not matches:
        return absent_string()

    def score(match: re.Match) -> tuple:
        line = _line_index(text, match.start())
        near_name = 1 if name is not None and line == name.line_index else 0
        near_strength = 0
        if strengths:
            near_strength = 1 if any(s.line_index == line and abs(s.start - match.start()) < 80 for s in strengths) else 0
        return (near_name, near_strength, -match.start())

    best = max(matches, key=score)
    line = _line_index(text, best.start())
    near_name = name is not None and line == name.line_index
    confidence = 0.9 if near_name else 0.75
    canonical = normalize_form(best.group(1)) or best.group(1).casefold()
    return FieldString(value=canonical, confidence=confidence, source="ocr", raw=best.group(1), normalized=True)


def find_manufacturer(text: str) -> FieldString:
    match = MANUFACTURER_RE.search(text)
    if not match:
        return absent_string()
    raw = match.group("name").strip().rstrip(".,;:")
    raw = re.split(r"\s{2,}|\n", raw)[0].strip()
    if len(raw) < 2:
        return absent_string()
    return FieldString(value=raw, confidence=0.6, source="ocr", raw=raw)


# --------------------------------------------------------------------------- #
# Dosage instructions
# --------------------------------------------------------------------------- #


def _segments(raw_text: str) -> list[str]:
    segments: list[str] = []
    for line in raw_text.split("\n"):
        for part in re.split(r"(?<=[.;!?])\s+", line):
            part = part.strip().strip("*•·▪–—").strip()
            part = re.sub(r"^(?:\(\d+\)|[a-z]\))\s*", "", part)
            part = part.strip().lstrip("-").strip()
            if part:
                segments.append(part)
    return segments


def _dose_is_valid(match: re.Match, segment: str) -> bool:
    """Reject package counts (``30 tablets``) while keeping real doses."""
    text = match.group(0)
    quantity = match.group("qty")
    if re.search(r"take|use", text, re.IGNORECASE):
        return True
    if re.search(r"(?:to|-)\s*\d", quantity):
        return True
    try:
        count = float(quantity)
    except ValueError:
        return False
    if count > 8:
        return False
    tail = segment[match.end() : match.end() + 30]
    if re.search(r"per\s*(?:bottle|container|pack)|in\s*each\s*bottle|bottle\s*of", tail, re.IGNORECASE):
        return False
    return True


def _merge(items: list[tuple[int, int, str, str]]) -> list[tuple[int, str, str]]:
    """Merge adjacent same-kind matches (e.g. ``every 4 hours`` + ``as needed``)."""
    merged: list[tuple[int, int, str, str]] = []
    for start, end, kind, text in sorted(items, key=lambda item: (item[0], _KIND_ORDER.get(item[2], 9))):
        if merged and merged[-1][2] == kind and start - merged[-1][1] <= 2:
            prev_start, _, _, prev_text = merged[-1]
            merged[-1] = (prev_start, end, kind, f"{prev_text} {text}")
        else:
            merged.append((start, end, kind, text))
    out: list[tuple[int, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for start, _, kind, text in sorted(merged, key=lambda item: (item[0], _KIND_ORDER.get(item[2], 9))):
        key = (kind, text)
        if key in seen:
            continue
        seen.add(key)
        out.append((start, kind, text))
    return out


def parse_instructions(raw_text: str) -> list[InstructionItem]:
    """Split raw label text into verbatim dosage-instruction items.

    Kinds: ``dose`` (quantity per dose), ``frequency``, ``route``, ``duration``,
    ``warning``, ``other``. Every item text is a substring of the source.
    Degenerate/unreadable text (no ASCII letters or < 3 alphabetic characters)
    returns ``[]`` instead of junk ``other`` items.
    """
    raw = "" if raw_text is None else str(raw_text)
    if not has_readable_content(raw):
        return []
    items: list[InstructionItem] = []
    for segment in _segments(raw):
        if WARNING_RE.search(segment):
            items.append(InstructionItem(kind=_WARNING_KIND, text=segment))
            continue
        found: list[tuple[int, int, str, str]] = []
        for match in DOSE_RE.finditer(segment):
            if _dose_is_valid(match, segment):
                found.append((match.start(), match.end(), "dose", match.group(0).strip()))
        for kind, pattern in (("frequency", FREQ_RE), ("route", ROUTE_RE), ("duration", DURATION_RE)):
            for match in pattern.finditer(segment):
                text = match.group(0).strip()
                if text:
                    found.append((match.start(), match.end(), kind, text))
        if not found:
            items.append(InstructionItem(kind="other", text=segment))
            continue
        for _, kind, text in _merge(found):
            items.append(InstructionItem(kind=kind, text=text))  # type: ignore[arg-type]
    return items


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def normalize_dose_unit(word: str | None) -> str | None:
    """Lowercase singular dose unit (``TABLETS`` -> ``tablet``, ``CAPS`` -> ``capsule``)."""
    if word is None:
        return None
    return DOSE_UNIT_CANONICAL.get(word.casefold(), word.casefold())


def _dose_from_segment(segment: str) -> tuple[float, str, float] | str | None:
    """Extract one unambiguous dose from a dose segment.

    Returns ``(quantity, unit, confidence)``, the string ``"ambiguous"`` for a
    range such as ``1 to 2 tablets``, or ``None`` when no dose quantity is stated.
    """
    if _DOSE_RANGE_RE.search(segment) and _DOSE_FORM_SEARCH_RE.search(segment):
        return "ambiguous"

    # Fractions must be checked before plain numbers ("1/2 tablet" contains "2 tablet").
    match = _FRACTION_DOSE_RE.search(segment)
    if match:
        numerator, denominator = int(match.group("num")), int(match.group("den"))
        if denominator == 0:
            return None
        quantity = int(match.group("whole") or 0) + numerator / denominator
        if quantity <= 0:
            return None
        return round(quantity, 4), normalize_dose_unit(match.group("form")) or "unit", 0.85

    match = _UNICODE_DOSE_RE.search(segment)
    if match:
        quantity = _UNICODE_FRACTIONS[match.group("frac")]
        return quantity, normalize_dose_unit(match.group("form")) or "unit", 0.85

    for match in DOSE_RE.finditer(segment):
        if not _dose_is_valid(match, segment):
            continue
        quantity_text = match.group("qty")
        if re.search(r"(?:to|-)\s*\d", quantity_text):
            return "ambiguous"
        quantity = float(quantity_text)
        if quantity <= 0:
            continue
        return quantity, normalize_dose_unit(match.group("form")) or "unit", 0.9

    match = _WORD_DOSE_RE.search(segment)
    if match:
        quantity = _QUANTITY_WORDS[match.group("qty").casefold()]
        if match.group("extra"):
            quantity += 0.5
        return round(quantity, 4), normalize_dose_unit(match.group("form")) or "unit", 0.75

    return None


def parse_dose_quantity(raw_text: str, instructions: list[InstructionItem] | None = None) -> tuple[float | None, str | None, float, str]:
    """Parse the structured per-dose quantity (contract v1.1 ``instructions.dose``).

    Only dose segments are considered: segments that already produced a ``dose``
    instruction item, or that carry a word/fraction quantity (e.g. ``half tablet``).
    Warning and package-count text is never treated as a dose. Ranges such as
    ``1 to 2 tablets`` return ``(None, None, 0.0, "none")`` — never a guessed number.
    """
    raw = "" if raw_text is None else str(raw_text)
    if not raw.strip():
        return None, None, 0.0, "none"

    if instructions is None:
        instructions = parse_instructions(raw)
    dose_texts = [item.text for item in instructions if item.kind == "dose"]

    for segment in _segments(raw):
        if WARNING_RE.search(segment):
            continue
        is_dose_segment = any(text and text in segment for text in dose_texts) or bool(
            _WORD_DOSE_RE.search(segment) or _FRACTION_DOSE_RE.search(segment) or _UNICODE_DOSE_RE.search(segment)
        )
        if not is_dose_segment:
            continue
        result = _dose_from_segment(segment)
        if result is None:
            continue
        if result == "ambiguous":
            return None, None, 0.0, "none"
        quantity, unit, confidence = result
        return quantity, unit, confidence, "ocr"
    return None, None, 0.0, "none"


def _clean_meta_value(text: str) -> str:
    """Trim surrounding whitespace/punctuation; result stays a source substring."""
    return text.strip().strip(" \t.,;:")


def _find_quantity_start(text: str) -> FieldString:
    match = QUANTITY_RE.search(text)
    if not match:
        return absent_string()
    return FieldString(value=match.group("value"), confidence=0.9, source="ocr", raw=match.group("value"))


def _find_refills(text: str) -> FieldString:
    match = REFILLS_RE.search(text)
    if match:
        return FieldString(value=match.group("value"), confidence=0.9, source="ocr", raw=match.group("value"))
    no_refills = NO_REFILLS_RE.search(text)
    if no_refills:
        return FieldString(value="0", confidence=0.85, source="ocr", raw="0")
    return absent_string()


def _find_pharmacy_name(text: str) -> FieldString:
    labeled = PHARMACY_LABEL_RE.search(text)
    if labeled:
        value = _clean_meta_value(labeled.group("value"))
        if value:
            return FieldString(value=value, confidence=0.8, source="ocr", raw=value)
    for line in text.split("\n"):
        if not PHARMACY_WORD_RE.search(line):
            continue
        candidate = re.split(r"\b(?:Tel|Phone|Ph)\b", line, maxsplit=1, flags=re.IGNORECASE)[0]
        candidate = _clean_meta_value(candidate)
        if candidate:
            return FieldString(value=candidate, confidence=0.75, source="ocr", raw=candidate)
    # Positional fallback: the line immediately above a phone line is the
    # pharmacy line on conventional pharmacy labels (e.g. "Sample Rx").
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if index == 0 or not PHONE_LABEL_RE.search(line):
            continue
        candidate = _clean_meta_value(lines[index - 1])
        if not candidate or len(candidate) > 40 or re.search(r"\d", candidate):
            continue
        if re.search(r"\b(?:only|refills?|prescriber|tablets?|capsules?)\b", candidate, re.IGNORECASE):
            continue
        return FieldString(value=candidate, confidence=0.6, source="ocr", raw=candidate)
    return absent_string()


def _find_pharmacy_phone(text: str) -> FieldString:
    labeled = PHONE_LABEL_RE.search(text)
    if labeled:
        value = _clean_meta_value(labeled.group("value"))
        if re.search(r"\d{3}", value):
            return FieldString(value=value, confidence=0.85, source="ocr", raw=value)
    generic = PHONE_GENERIC_RE.search(text)
    if generic:
        value = _clean_meta_value(generic.group("value"))
        return FieldString(value=value, confidence=0.6, source="ocr", raw=value)
    return absent_string()


def _find_prescriber(text: str) -> FieldString:
    labeled = PRESCRIBER_RE.search(text)
    if labeled:
        value = _clean_meta_value(labeled.group("value"))
        if value:
            return FieldString(value=value, confidence=0.85, source="ocr", raw=value)
    doctor = PRESCRIBER_DR_RE.search(text)
    if doctor:
        value = _clean_meta_value(doctor.group("value"))
        if value:
            return FieldString(value=value, confidence=0.7, source="ocr", raw=value)
    return absent_string()


def _derive_schedule_times(instructions: list[InstructionItem]) -> FieldString:
    """Convert a parsed frequency into times; derived, so confidence is base x 0.8.

    Unsupported cadences (weekly, every N hours/days, every other day, PRN) are
    skipped; if nothing left maps, the field stays absent rather than guessed.
    """
    for item in instructions:
        if item.kind != "frequency":
            continue
        if _SCHEDULE_UNSUPPORTED_RE.search(item.text):
            continue
        for pattern, times in _SCHEDULE_PATTERNS:
            if pattern.search(item.text):
                return FieldString(
                    value=times,
                    confidence=round(SCHEDULE_BASE_CONFIDENCE * SCHEDULE_DERIVATION_FACTOR, 4),
                    source="ocr",
                    raw=item.text,
                )
    return absent_string()


def parse_label_meta(raw_text: str, instructions: list[InstructionItem] | None = None) -> dict[str, FieldString]:
    """Extract contract v1.3 ``label_meta`` fields from raw label text.

    String values are substrings of the source text (schedule_times is derived
    from the parsed frequency and documented as such). Missing fields return the
    absent shape: value None, confidence 0.0, source "none".
    """
    raw = "" if raw_text is None else str(raw_text)
    if not has_readable_content(raw):
        return {key: absent_string() for key in LABEL_META_KEYS}
    if instructions is None:
        instructions = parse_instructions(raw)
    return {
        "quantity_start": _find_quantity_start(raw),
        "refills_remaining": _find_refills(raw),
        "pharmacy_name": _find_pharmacy_name(raw),
        "pharmacy_phone": _find_pharmacy_phone(raw),
        "prescriber": _find_prescriber(raw),
        "schedule_times": _derive_schedule_times(instructions),
    }


def extract_fields(raw_text: str, hints: dict[str, Any] | None = None) -> Extraction:
    """Extract name / strength / form / manufacturer and parsed instructions.

    Args:
        raw_text: verbatim OCR text (multi-line labels use ``"\\n"``).
        hints: optional biases, never sources of values. Supported keys:
            ``name`` (expected name), ``lexicon`` (extra names to recognize),
            ``strength_value`` / ``strength_unit`` (expected strength).
    """
    hints = hints or {}
    raw = "" if raw_text is None else str(raw_text)
    if not has_readable_content(raw):
        # Unread label (e.g. a lone CJK false positive): return an empty
        # extraction rather than junk items. raw_text is preserved verbatim.
        return Extraction(
            raw_text=raw,
            name=absent_string(),
            strength=absent_strength(),
            form=absent_string(),
            instructions=[],
            label_meta=parse_label_meta(raw),
        )

    extra_names = hints.get("lexicon") or ()
    name_hint = hints.get("name")
    strengths = find_strengths(raw)
    name_match = find_name(raw, extra_names=extra_names, name_hint=name_hint)

    if name_match is None:
        name_field = absent_string()
    else:
        name_field = FieldString(
            value=name_match.value,
            confidence=_name_confidence(name_match, name_hint),
            source="ocr",
            raw=name_match.raw,
            normalized=name_match.normalized,
        )

    strength_field = _select_strength(strengths, name_match.line_index if name_match else None, hints)
    form_field = find_form(raw, name_match, strengths)
    manufacturer = find_manufacturer(raw)
    instructions = parse_instructions(raw)
    dose_quantity, dose_unit, dose_confidence, dose_source = parse_dose_quantity(raw, instructions)
    label_meta = parse_label_meta(raw, instructions)
    return Extraction(
        raw_text=raw,
        name=name_field,
        strength=strength_field,
        form=form_field,
        manufacturer=manufacturer,
        instructions=instructions,
        dose_quantity=dose_quantity,
        dose_unit=dose_unit,
        dose_confidence=dose_confidence,
        dose_source=dose_source,
        label_meta=label_meta,
    )


__all__ = [
    "DRUG_NAMES",
    "extract_fields",
    "find_form",
    "find_manufacturer",
    "find_name",
    "find_strengths",
    "normalize_dose_unit",
    "parse_dose_quantity",
    "parse_instructions",
    "parse_label_meta",
]
