"""MedCheck OCR service (owner: PI-2 Orion).

Public API::

    from services.ocr import read_text, extract_fields, parse_instructions
"""

from .engine import BACKEND_NAME, OcrUnavailableError, is_available, read_text
from .extract import (
    extract_fields,
    find_form,
    find_manufacturer,
    find_name,
    find_strengths,
    normalize_dose_unit,
    parse_dose_quantity,
    parse_instructions,
    parse_label_meta,
)
from .fuse import FusionResult, extraction_confidence, fuse_extractions
from .matcher import DEFAULT_THRESHOLD, match_candidates
from .types import (
    BBox,
    Extraction,
    FieldString,
    FieldStrength,
    InstructionItem,
    LABEL_META_KEYS,
    OcrLine,
    OcrResult,
    OcrWord,
    has_readable_content,
)

__all__ = [
    "BACKEND_NAME",
    "BBox",
    "DEFAULT_THRESHOLD",
    "Extraction",
    "FieldString",
    "FieldStrength",
    "FusionResult",
    "InstructionItem",
    "LABEL_META_KEYS",
    "OcrLine",
    "OcrResult",
    "OcrUnavailableError",
    "OcrWord",
    "extract_fields",
    "extraction_confidence",
    "find_form",
    "find_manufacturer",
    "find_name",
    "find_strengths",
    "fuse_extractions",
    "has_readable_content",
    "is_available",
    "match_candidates",
    "normalize_dose_unit",
    "parse_dose_quantity",
    "parse_instructions",
    "parse_label_meta",
    "read_text",
]
