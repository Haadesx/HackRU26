"""Synthetic mock fixture set for the MedCheck API gateway.

These labels are fabricated for testing only. No real patient data is used.
Mock mode may only return medication names present in this file — it must never
fabricate a drug name outside this set (contracts/README.md rule 5).
"""
from __future__ import annotations

from typing import Any, Dict, List

# Each fixture is a partial ScanResponse payload (timing/request_id/safety and
# mode are added by the pipeline). Every fixture includes blur/exposure/glare so
# the serialized response satisfies contracts/v1/scan_response.schema.json.
FIXTURES: List[Dict[str, Any]] = [
    {
        "key": "metformin_ok",
        "status": "ok",
        "frame_quality": {
            "acceptable": True,
            "score": 0.91,
            "blur": {"score": 0.93, "is_blurry": False},
            "exposure": {"score": 0.90, "too_dark": False, "too_bright": False},
            "glare": {"score": 0.88, "has_glare": False},
            "guidance": [],
        },
        "bottle": {
            "detected": True,
            "confidence": 0.95,
            "bbox": {"x": 0.14, "y": 0.18, "w": 0.52, "h": 0.64},
        },
        "label": {
            "detected": True,
            "confidence": 0.89,
            "bbox": {"x": 0.20, "y": 0.24, "w": 0.42, "h": 0.50},
            "text": (
                "METFORMIN HCl 500 mg TABLETS\n"
                "Take 1 tablet by mouth twice daily with meals.\n"
                "Rx only"
            ),
        },
        "medication": {
            "name": {"value": "Metformin", "confidence": 0.92, "source": "ocr"},
            "strength": {"value": 500, "unit": "mg", "confidence": 0.90, "source": "ocr"},
            "form": {"value": "tablet", "confidence": 0.85, "source": "ocr"},
            "manufacturer": {"value": None, "confidence": 0.0, "source": "none"},
        },
        "instructions": {
            "raw_text": "Take 1 tablet by mouth twice daily with meals.",
            "parsed": [
                {"kind": "dose", "text": "1 tablet"},
                {"kind": "route", "text": "by mouth"},
                {"kind": "frequency", "text": "twice daily"},
                {"kind": "other", "text": "with meals"},
            ],
            "dose": {"quantity": 1, "unit": "tablet", "confidence": 0.9, "source": "ocr"},
        },
        "candidates": [
            {
                "name": "Metformin",
                "strength": {"value": 500, "unit": "mg"},
                "score": 0.92,
                "source": "registry",
            }
        ],
        "label_meta": {
            "quantity_start": {"value": "30", "confidence": 0.95, "source": "ocr"},
            "refills_remaining": {"value": "2", "confidence": 0.9, "source": "ocr"},
            "pharmacy_name": {"value": "Demo Pharmacy", "confidence": 0.88, "source": "ocr"},
            "pharmacy_phone": {"value": "(555) 010-2030", "confidence": 0.85, "source": "ocr"},
            "prescriber": {"value": "Dr. A. Demo", "confidence": 0.8, "source": "ocr"},
            "schedule_times": {"value": "08:00, 20:00", "confidence": 0.7, "source": "ocr"},
        },
        "interpretation": {"available": False, "summary": None, "source": None, "model": None},
        "uncertainty": {"level": "low", "reasons": [], "rescan_required": False},
    },
    {
        "key": "amoxicillin_ok",
        "status": "ok",
        "frame_quality": {
            "acceptable": True,
            "score": 0.87,
            "blur": {"score": 0.90, "is_blurry": False},
            "exposure": {"score": 0.86, "too_dark": False, "too_bright": False},
            "glare": {"score": 0.83, "has_glare": False},
            "guidance": [],
        },
        "bottle": {
            "detected": True,
            "confidence": 0.93,
            "bbox": {"x": 0.18, "y": 0.16, "w": 0.48, "h": 0.66},
        },
        "label": {
            "detected": True,
            "confidence": 0.86,
            "bbox": {"x": 0.23, "y": 0.22, "w": 0.40, "h": 0.52},
            "text": (
                "AMOXICILLIN 500 mg CAPSULES\n"
                "Take one capsule three times daily for 7 days.\n"
                "Store at room temperature."
            ),
        },
        "medication": {
            "name": {"value": "Amoxicillin", "confidence": 0.90, "source": "ocr"},
            "strength": {"value": 500, "unit": "mg", "confidence": 0.88, "source": "ocr"},
            "form": {"value": "capsule", "confidence": 0.82, "source": "ocr"},
            "manufacturer": {"value": None, "confidence": 0.0, "source": "none"},
        },
        "instructions": {
            "raw_text": "Take one capsule three times daily for 7 days.",
            "parsed": [
                {"kind": "dose", "text": "one capsule"},
                {"kind": "frequency", "text": "three times daily"},
                {"kind": "duration", "text": "7 days"},
            ],
            "dose": {"quantity": 1, "unit": "capsule", "confidence": 0.88, "source": "ocr"},
        },
        "candidates": [
            {
                "name": "Amoxicillin",
                "strength": {"value": 500, "unit": "mg"},
                "score": 0.90,
                "source": "registry",
            }
        ],
        "label_meta": {
            "quantity_start": {"value": "21", "confidence": 0.9, "source": "ocr"},
            "refills_remaining": {"value": "0", "confidence": 0.9, "source": "ocr"},
            "pharmacy_name": {"value": "Demo Pharmacy", "confidence": 0.85, "source": "ocr"},
            "pharmacy_phone": {"value": "(555) 010-2030", "confidence": 0.85, "source": "ocr"},
            "prescriber": {"value": "Dr. A. Demo", "confidence": 0.8, "source": "ocr"},
            "schedule_times": {"value": "08:00, 14:00, 20:00", "confidence": 0.7, "source": "ocr"},
        },
        "interpretation": {"available": False, "summary": None, "source": None, "model": None},
        "uncertainty": {"level": "low", "reasons": [], "rescan_required": False},
    },
    {
        "key": "ibuprofen_uncertain",
        "status": "uncertain",
        "frame_quality": {
            "acceptable": True,
            "score": 0.62,
            "blur": {"score": 0.58, "is_blurry": False},
            "exposure": {"score": 0.80, "too_dark": False, "too_bright": False},
            "glare": {"score": 0.75, "has_glare": False},
            "guidance": ["Hold the bottle steady", "Move closer so the label fills the frame"],
        },
        "bottle": {
            "detected": True,
            "confidence": 0.78,
            "bbox": {"x": 0.20, "y": 0.20, "w": 0.46, "h": 0.60},
        },
        "label": {
            "detected": True,
            "confidence": 0.54,
            "bbox": {"x": 0.25, "y": 0.26, "w": 0.38, "h": 0.46},
            "text": "IBUPROFEN 200 mg TABLETS\nTake 1 tablet every 6 to 8 hours as needed.\nDo not exceed 6 tablets in 24 hours.",
        },
        "medication": {
            "name": {"value": "Ibuprofen", "confidence": 0.55, "source": "ocr"},
            "strength": {"value": 200, "unit": "mg", "confidence": 0.60, "source": "ocr"},
            "form": {"value": "tablet", "confidence": 0.50, "source": "ocr"},
            "manufacturer": {"value": None, "confidence": 0.0, "source": "none"},
        },
        "instructions": {
            "raw_text": "Take 1 tablet every 6 to 8 hours as needed.",
            "parsed": [
                {"kind": "dose", "text": "1 tablet"},
                {"kind": "frequency", "text": "every 6 to 8 hours as needed"},
            ],
            "dose": {"quantity": 1, "unit": "tablet", "confidence": 0.6, "source": "ocr"},
        },
        "candidates": [
            {
                "name": "Ibuprofen",
                "strength": {"value": 200, "unit": "mg"},
                "score": 0.58,
                "source": "registry",
            }
        ],
        "label_meta": {
            "quantity_start": {"value": "60", "confidence": 0.6, "source": "ocr"},
            "refills_remaining": {"value": None, "confidence": 0.0, "source": "none"},
            "pharmacy_name": {"value": "Demo Pharmacy", "confidence": 0.6, "source": "ocr"},
            "pharmacy_phone": {"value": "(555) 010-2030", "confidence": 0.6, "source": "ocr"},
            "prescriber": {"value": None, "confidence": 0.0, "source": "none"},
            "schedule_times": {"value": "08:00, 20:00", "confidence": 0.5, "source": "ocr"},
        },
        "interpretation": {"available": False, "summary": None, "source": None, "model": None},
        "uncertainty": {
            "level": "medium",
            "reasons": ["low_ocr_confidence"],
            "rescan_required": False,
        },
    },
    {
        "key": "blurry_rescan",
        "status": "needs_rescan",
        "frame_quality": {
            "acceptable": False,
            "score": 0.31,
            "blur": {"score": 0.22, "is_blurry": True},
            "exposure": {"score": 0.70, "too_dark": True, "too_bright": False},
            "glare": {"score": 0.85, "has_glare": False},
            "guidance": [
                "Hold the bottle steady",
                "Move closer so the label fills the frame",
                "Find more light",
            ],
        },
        "bottle": {
            "detected": True,
            "confidence": 0.81,
            "bbox": {"x": 0.30, "y": 0.35, "w": 0.40, "h": 0.45},
        },
        "label": {"detected": False, "confidence": 0.20, "text": None},
        "medication": {
            "name": {"value": None, "confidence": 0.0, "source": "none"},
        },
        "instructions": {"raw_text": None, "parsed": []},
        "candidates": [],
        "interpretation": {"available": False, "summary": None, "source": None, "model": None},
        "uncertainty": {
            "level": "high",
            "reasons": ["frame_too_blurry", "label_not_readable"],
            "rescan_required": True,
        },
    },
    {
        "key": "no_bottle",
        "status": "no_medication_found",
        "frame_quality": {
            "acceptable": True,
            "score": 0.84,
            "blur": {"score": 0.90, "is_blurry": False},
            "exposure": {"score": 0.86, "too_dark": False, "too_bright": False},
            "glare": {"score": 0.80, "has_glare": False},
            "guidance": [
                "Point the camera at a medication bottle",
                "Fill the frame with the label",
            ],
        },
        "bottle": {"detected": False, "confidence": 0.05},
        "label": {"detected": False, "confidence": 0.05, "text": None},
        "medication": {
            "name": {"value": None, "confidence": 0.0, "source": "none"},
        },
        "instructions": {"raw_text": None, "parsed": []},
        "candidates": [],
        "interpretation": {"available": False, "summary": None, "source": None, "model": None},
        "uncertainty": {
            "level": "high",
            "reasons": ["no_bottle_detected", "no_label_detected"],
            "rescan_required": True,
        },
    },
]


def fixture_by_key(key: str) -> Dict[str, Any]:
    """Return the fixture with the given key (raises KeyError if absent)."""
    for fixture in FIXTURES:
        if fixture["key"] == key:
            return fixture
    raise KeyError(key)
