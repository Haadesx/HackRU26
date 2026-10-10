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
)
from .matcher import DEFAULT_THRESHOLD, match_candidates
from .types import (
    BBox,
    Extraction,
    FieldString,
    FieldStrength,
    InstructionItem,
    OcrLine,
    OcrResult,
    OcrWord,
)

__all__ = [
    "BACKEND_NAME",
    "BBox",
    "DEFAULT_THRESHOLD",
    "Extraction",
    "FieldString",
    "FieldStrength",
    "InstructionItem",
    "OcrLine",
    "OcrResult",
    "OcrUnavailableError",
    "OcrWord",
    "extract_fields",
    "find_form",
    "find_manufacturer",
    "find_name",
    "find_strengths",
    "is_available",
    "match_candidates",
    "normalize_dose_unit",
    "parse_dose_quantity",
    "parse_instructions",
    "read_text",
]
