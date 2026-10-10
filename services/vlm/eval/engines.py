"""Pluggable OCR/VLM engines used by the OCR-vs-VLM evaluation.

The OCR baseline here is a local Tesseract reader with a small line-based field
parser. It exists to give the evaluation a real, reproducible OCR column; the
product OCR/extraction stack is owned by PI-2 (services/ocr) and will replace
this baseline via the same ``OcrEngine`` protocol.
"""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from services.vlm.client import VlmResult

CANONICAL_FIELDS = (
    "name",
    "strength_value",
    "strength_unit",
    "form",
    "manufacturer",
    "instructions",
)


@dataclass(frozen=True)
class TextLine:
    text: str
    confidence: float = 0.8


@dataclass
class OcrRead:
    text: str
    fields: Dict[str, Dict[str, Any]]
    latency_ms: float = 0.0
    engine: str = "unknown"
    error: Optional[str] = None


class OcrEngine(Protocol):
    name: str

    def read(self, image_bytes: bytes) -> OcrRead:  # pragma: no cover - protocol
        ...


def _entry(value: Any, confidence: float) -> Dict[str, Any]:
    return {"value": value, "confidence": round(float(confidence), 3), "source": "ocr"}


_HEADER_PATTERNS = (
    "synthetic label",
    "medcheck pharmacy",
    "rx #",
    "synthetic patient",
    "not for dispensing",
)
_STRENGTH_RE = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mcg|µg|ug|mg|ml|g|iu|%)\b", re.IGNORECASE
)
_FORM_RE = re.compile(r"\b(tablet|capsule|caplet|syrup|cream|injection|drops)\b", re.IGNORECASE)
_MFR_RE = re.compile(r"\bMFR\s*:?\s*(?P<value>.+?)\s*$", re.IGNORECASE)
_TAKE_RE = re.compile(r"\bTAKE\s*:?\s*(?P<rest>.*)$", re.IGNORECASE)
_STOP_RE = re.compile(r"^(MFR|QTY|REFILLS|LOT|EXP|INFORMATIONAL)\b", re.IGNORECASE)


def normalize_unit(unit: str) -> str:
    unit = unit.strip().lower()
    return {"µg": "mcg", "ug": "mcg"}.get(unit, unit)


def parse_label_fields(
    lines: List[TextLine], default_confidence: float = 0.8
) -> Dict[str, Dict[str, Any]]:
    """Heuristic line-based extraction used as the OCR baseline."""
    fields: Dict[str, Dict[str, Any]] = {}
    clean = [TextLine(re.sub(r"\s+", " ", ln.text).strip(), ln.confidence) for ln in lines]

    strength_idx: Optional[int] = None
    for i, line in enumerate(clean):
        match = _STRENGTH_RE.search(line.text)
        if match and strength_idx is None:
            strength_idx = i
            value = float(match.group("value"))
            fields["strength_value"] = _entry(int(value) if value.is_integer() else value, line.confidence)
            fields["strength_unit"] = _entry(normalize_unit(match.group("unit")), line.confidence)

    if strength_idx is not None:
        for j in range(strength_idx - 1, max(-1, strength_idx - 4), -1):
            text = clean[j].text
            low = text.lower()
            if not text or any(pat in low for pat in _HEADER_PATTERNS):
                continue
            if _FORM_RE.fullmatch(low) or _STRENGTH_RE.search(text) or _TAKE_RE.search(text):
                continue
            fields["name"] = _entry(text, clean[j].confidence)
            break

    if "form" not in fields:
        for line in clean:
            match = _FORM_RE.search(line.text)
            if match:
                fields["form"] = _entry(match.group(1).capitalize(), line.confidence)
                break

    for line in clean:
        match = _MFR_RE.search(line.text)
        if match:
            fields["manufacturer"] = _entry(match.group("value").strip(" ."), line.confidence)
            break

    # Instructions: "TAKE:" plus following lines until the footer block starts.
    for i, line in enumerate(clean):
        match = _TAKE_RE.search(line.text)
        if not match:
            continue
        pieces = [match.group("rest").strip()]
        confidences = [line.confidence]
        for nxt in clean[i + 1 : i + 4]:
            if _STOP_RE.match(nxt.text):
                break
            pieces.append(nxt.text)
            confidences.append(nxt.confidence)
        text = " ".join(piece for piece in pieces if piece)
        if text:
            fields["instructions"] = _entry(text, min(confidences))
        break

    return fields


class TesseractOCR:
    """Local Tesseract baseline; raises OcrUnavailable when the binary is missing."""

    name = "tesseract"

    def __init__(self, lang: str = "eng"):
        if shutil.which("tesseract") is None:
            raise OcrUnavailable("tesseract binary not found on PATH")
        self.lang = lang

    def read(self, image_bytes: bytes) -> OcrRead:
        import pytesseract
        from PIL import Image

        started = time.perf_counter()
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            data = pytesseract.image_to_data(image, lang=self.lang, output_type=pytesseract.Output.DICT)
        except Exception as exc:  # pragma: no cover - environment dependent
            return OcrRead(
                text="",
                fields={},
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                engine=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

        grouped: Dict[tuple, List[TextLine]] = {}
        for i, word in enumerate(data.get("text", [])):
            word = (word or "").strip()
            if not word:
                continue
            try:
                confidence = max(0.0, min(1.0, float(data["conf"][i]) / 100.0))
            except (TypeError, ValueError):
                confidence = 0.0
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            grouped.setdefault(key, []).append(TextLine(word, confidence))

        lines: List[TextLine] = []
        for key in sorted(grouped):
            words = grouped[key]
            lines.append(TextLine(" ".join(w.text for w in words), min(w.confidence for w in words)))

        text = "\n".join(line.text for line in lines)
        return OcrRead(
            text=text,
            fields=parse_label_fields(lines),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            engine=self.name,
        )


class GroundTruthOCR:
    """Control engine: returns the dataset ground truth (upper bound for OCR)."""

    name = "ground_truth"

    def __init__(self, truth_by_sha: Dict[str, Dict[str, Any]]):
        self._truth = truth_by_sha

    def read(self, image_bytes: bytes) -> OcrRead:
        truth = self._truth.get(hashlib.sha256(image_bytes).hexdigest(), {})
        fields = {key: _entry(truth[key], 1.0) for key in CANONICAL_FIELDS if truth.get(key) is not None}
        text = " ".join(str(value) for value in truth.values())
        return OcrRead(text=text, fields=fields, latency_ms=0.0, engine=self.name)


class TruthVLM:
    """Control VLM: returns ground truth as a successful VlmResult (no network).

    Used for harness validation and tests, never for product paths.
    """

    def __init__(self, truth_by_sha: Dict[str, Dict[str, Any]], model: str = "truth-control"):
        self._truth = truth_by_sha
        self.model = model
        self.calls = 0

    def interpret(self, image_bytes: bytes, ocr_text: Optional[str] = None, question: Optional[str] = None) -> VlmResult:
        self.calls += 1
        truth = self._truth.get(hashlib.sha256(image_bytes).hexdigest(), {})
        fields = {key: _entry(truth[key], 0.95) for key in CANONICAL_FIELDS if truth.get(key) is not None}
        return VlmResult(
            available=True,
            summary="ground-truth control",
            fields=fields,
            raw_text="",
            model=self.model,
            latency_ms=0.0,
        )


class OcrUnavailable(RuntimeError):
    """Raised when the local OCR baseline cannot run in this environment."""
