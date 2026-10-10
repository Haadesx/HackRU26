"""Vision service configuration and hint parsing.

`analyze_frame(image_bytes, hints)` accepts a plain dict so callers (the API
gateway) stay decoupled from this model. Hints that match a `VisionConfig`
field override the defaults; unknown hint keys are ignored on purpose so the
API can pass forward-compatible metadata.

Environment:
    MEDCHECK_YOLO_MODEL — path to YOLO-class weights. Used as the default
    `model_path` when hints do not provide one. Unset => deterministic CPU
    heuristic fallback (no torch import).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DetectorKind = Literal["auto", "heuristic", "yolo", "none"]
DeviceKind = Literal["auto", "cpu", "cuda"]

#: Environment variable holding YOLO weights path.
YOLO_MODEL_ENV = "MEDCHECK_YOLO_MODEL"
#: Environment variable holding the YOLO confidence threshold (both backends).
YOLO_CONF_ENV = "MEDCHECK_YOLO_CONF"
DEFAULT_YOLO_CONF = 0.25


def yolo_confidence_threshold(default: float = DEFAULT_YOLO_CONF) -> float:
    """Read `MEDCHECK_YOLO_CONF`; invalid or out-of-range values fall back to `default`."""
    raw = os.environ.get(YOLO_CONF_ENV)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if not 0.0 < value <= 1.0:
        return default
    return value


class VisionConfig(BaseModel):
    """Tunables for one `analyze_frame` call."""

    model_config = ConfigDict(extra="forbid")

    #: Longest side of the analysis image. Larger inputs are downscaled, never upscaled.
    max_side: int = Field(1280, ge=64, le=4096)
    #: Apply CLAHE luminance equalization (off by default; deterministic either way).
    clahe: bool = False
    #: Apply light denoising (off by default; slow on large frames).
    denoise: bool = False
    #: Detector selection. "auto" uses YOLO when `model_path` is given and the
    #: optional ultralytics dependency imports, else the CPU heuristic.
    detector: DetectorKind = "auto"
    #: Path to YOLO-class weights. Never bundled in git; ignored by the heuristic.
    #: Defaults to $MEDCHECK_YOLO_MODEL when that environment variable is set.
    model_path: Optional[str] = Field(default_factory=lambda: os.environ.get(YOLO_MODEL_ENV) or None)
    #: "cuda" is honored only when torch reports a GPU; everything else runs CPU.
    device: DeviceKind = "auto"

    @classmethod
    def from_hints(cls, hints: Optional[Dict[str, Any]]) -> "VisionConfig":
        if hints is None:
            return cls()
        if not isinstance(hints, dict):
            raise TypeError("hints must be a dict or None")
        known = set(cls.model_fields)
        values = {k: v for k, v in hints.items() if k in known and v is not None}
        return cls(**values)
