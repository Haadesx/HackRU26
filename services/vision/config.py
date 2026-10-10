"""Vision service configuration and hint parsing.

`analyze_frame(image_bytes, hints)` accepts a plain dict so callers (the API
gateway) stay decoupled from this model. Hints that match a `VisionConfig`
field override the defaults; unknown hint keys are ignored on purpose so the
API can pass forward-compatible metadata.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DetectorKind = Literal["auto", "heuristic", "yolo", "none"]
DeviceKind = Literal["auto", "cpu", "cuda"]


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
    model_path: Optional[str] = None
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
