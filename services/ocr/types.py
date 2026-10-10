"""Typed results for the MedCheck OCR stage (contract v1 aligned).

All boxes are normalized ``[0, 1]`` relative to the full input frame, matching
``contracts/v1/scan_response.schema.json`` -> ``definitions.bbox``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

FieldSource = Literal["ocr", "vlm", "registry", "none"]
InstructionKind = Literal["dose", "frequency", "route", "duration", "warning", "other"]


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def has_readable_content(text: str | None) -> bool:
    """True when OCR text has enough alphabetic content to be worth parsing.

    Unreadable text (lone CJK glyphs such as ``日``, ``||``, punctuation-only, or
    fewer than three alphabetic characters total) is treated as an unread label:
    the raw text is still preserved verbatim, but confidence collapses to 0 and
    extraction returns empty fields instead of junk items.

    Requires at least one ASCII letter AND at least three alphabetic characters
    overall (any script).
    """
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    ascii_letters = sum(1 for ch in stripped if ch.isascii() and ch.isalpha())
    alphabetic = sum(1 for ch in stripped if ch.isalpha())
    return ascii_letters > 0 and alphabetic >= 3


@dataclass(frozen=True)
class BBox:
    """Normalized ``[0, 1]`` box relative to the full frame (contract v1)."""

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_xyxy(
        cls,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        image_w: int,
        image_h: int,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> "BBox":
        """Build a normalized box from pixel corners in a (possibly cropped) frame."""
        if image_w <= 0 or image_h <= 0:
            raise ValueError("image dimensions must be positive")
        left, right = (x1, x2) if x1 <= x2 else (x2, x1)
        top, bottom = (y1, y2) if y1 <= y2 else (y2, y1)
        left = min(float(image_w), max(0.0, left + offset_x))
        right = min(float(image_w), max(0.0, right + offset_x))
        top = min(float(image_h), max(0.0, top + offset_y))
        bottom = min(float(image_h), max(0.0, bottom + offset_y))
        return cls(
            x=_clamp01(left / image_w),
            y=_clamp01(top / image_h),
            w=_clamp01(max(0.0, right - left) / image_w),
            h=_clamp01(max(0.0, bottom - top) / image_h),
        )

    @classmethod
    def from_points(
        cls,
        points: Sequence[Sequence[float]],
        image_w: int,
        image_h: int,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ) -> "BBox":
        """Build a normalized box from 4 corner points (any order)."""
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        return cls.from_xyxy(min(xs), min(ys), max(xs), max(ys), image_w, image_h, offset_x, offset_y)

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h

    def to_pixels(self, image_w: int, image_h: int) -> tuple[int, int, int, int]:
        """Return clamped ``(x1, y1, x2, y2)`` pixel coordinates (x2/y2 exclusive)."""
        x1 = int(round(self.x * image_w))
        y1 = int(round(self.y * image_h))
        x2 = int(round(self.x2 * image_w))
        y2 = int(round(self.y2 * image_h))
        x1 = max(0, min(image_w, x1))
        y1 = max(0, min(image_h, y1))
        x2 = max(0, min(image_w, x2))
        y2 = max(0, min(image_h, y2))
        return x1, y1, x2, y2

    def as_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(frozen=True)
class OcrWord:
    """Word-level result. Only produced when the backend exposes word boxes."""

    text: str
    confidence: float
    bbox: BBox | None = None


@dataclass(frozen=True)
class OcrLine:
    text: str
    confidence: float
    bbox: BBox | None = None
    words: tuple[OcrWord, ...] = ()


@dataclass
class OcrResult:
    """Raw OCR output. ``raw_text`` is the verbatim join of line texts."""

    raw_text: str
    lines: list[OcrLine] = field(default_factory=list)
    engine: str = "unknown"
    elapsed_ms: float = 0.0
    image_size: tuple[int, int] | None = None

    def __bool__(self) -> bool:
        return bool(self.raw_text.strip())

    @property
    def confidence(self) -> float:
        if not has_readable_content(self.raw_text):
            return 0.0
        if not self.lines:
            return 0.0
        return round(sum(line.confidence for line in self.lines) / len(self.lines), 4)

    @property
    def readable(self) -> bool:
        """False for degenerate recognition results (text stays verbatim)."""
        return has_readable_content(self.raw_text)


@dataclass(frozen=True)
class FieldString:
    """String field matching contract ``field_string``.

    ``raw`` keeps the verbatim source substring; ``normalized`` records whether
    ``value`` was canonicalized through the standard-name lexicon.
    """

    value: str | None
    confidence: float
    source: FieldSource = "ocr"
    raw: str | None = None
    normalized: bool = False

    def to_contract(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
        }


def absent_string() -> FieldString:
    """Not-found field, contract-valid (``source: "none"``)."""
    return FieldString(value=None, confidence=0.0, source="none")


@dataclass(frozen=True)
class FieldStrength:
    """Strength field matching contract ``field_strength`` (value + unit)."""

    value: float | None
    unit: str | None
    confidence: float
    source: FieldSource = "ocr"
    raw: str | None = None

    def to_contract(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
        }


def absent_strength() -> FieldStrength:
    return FieldStrength(value=None, unit=None, confidence=0.0, source="none")


@dataclass(frozen=True)
class InstructionItem:
    """One parsed dosage-instruction fragment; ``text`` is a verbatim substring."""

    kind: InstructionKind
    text: str

    def to_contract(self) -> dict[str, str]:
        return {"kind": self.kind, "text": self.text}


@dataclass
class Extraction:
    """Structured extraction result for a raw label text."""

    raw_text: str
    name: FieldString
    strength: FieldStrength
    form: FieldString
    manufacturer: FieldString = field(default_factory=absent_string)
    instructions: list[InstructionItem] = field(default_factory=list)
    # v1.1 additive: structured per-dose quantity (never a package count).
    dose_quantity: float | None = None
    dose_unit: str | None = None
    dose_confidence: float = 0.0
    dose_source: FieldSource = "none"

    def medication_contract(self) -> dict[str, Any]:
        """Contract fragment for ``ScanResponse.medication``."""
        return {
            "name": self.name.to_contract(),
            "strength": self.strength.to_contract(),
            "form": self.form.to_contract(),
            "manufacturer": self.manufacturer.to_contract(),
        }

    def dose_contract(self) -> dict[str, Any]:
        """Contract fragment for ``ScanResponse.instructions.dose`` (v1.1)."""
        return {
            "quantity": self.dose_quantity,
            "unit": self.dose_unit,
            "confidence": round(float(self.dose_confidence), 4),
            "source": self.dose_source,
        }

    def instructions_contract(self) -> dict[str, Any]:
        """Contract fragment for ``ScanResponse.instructions``."""
        return {
            "raw_text": self.raw_text,
            "parsed": [item.to_contract() for item in self.instructions],
            "dose": self.dose_contract(),
        }
