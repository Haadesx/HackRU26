"""Pydantic result models for the vision service.

`VisionResult` is the hand-off between `services/vision` and the API gateway.
`FrameQuality`, `Bottle`, `Label` and `Timing` are imported from the frozen v1
contract (`services/common/contract.py`) so the API can embed them without
translation. Bounding boxes are normalized `[0,1]` floats of the full frame.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field

from services.common.contract import Bottle, FrameQuality, Label, Timing


class FrameInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=1, description="Analysis frame width in pixels.")
    height: int = Field(ge=1, description="Analysis frame height in pixels.")
    original_width: int = Field(ge=1)
    original_height: int = Field(ge=1)
    scale: float = Field(gt=0, description="Analysis width / original width.")
    applied: List[str] = Field(default_factory=list, description="Preprocessing steps applied, in order.")


class VisionResult(BaseModel):
    """Everything the API needs from PI-1 VISION for one scan frame."""

    model_config = ConfigDict(extra="forbid")

    quality: FrameQuality
    bottle: Bottle
    label: Label
    #: True when the detected label touches the frame edge (label likely continues).
    label_clipped: bool = False
    #: Combined, ordered camera guidance (quality first, then detection/label).
    guidance: List[str] = Field(default_factory=list)
    timing: Timing
    #: Detector that actually produced `bottle` ("yolo", "heuristic" or "none").
    detector: str = "heuristic"
    frame: FrameInfo
