"""Tiny CLI demo for integration debugging.

    python -m services.vision.demo samples/label_metformin.png

Prints a JSON summary of the frame quality, bottle/label detections, camera
guidance and timing. Exits 1 and prints a JSON error on stderr when the image
cannot be read or decoded.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.vision.models import VisionResult
from services.vision.pipeline import analyze_frame


def build_summary(image_path: Path, result: VisionResult) -> Dict[str, Any]:
    """JSON-serializable summary for one `VisionResult`."""
    return {
        "file": str(image_path),
        "detector": result.detector,
        "frame": result.frame.model_dump(),
        "quality": result.quality.model_dump(),
        "bottle": result.bottle.model_dump(),
        "label": result.label.model_dump(),
        "guidance": list(result.guidance),
        "timing": result.timing.model_dump(),
    }


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m services.vision.demo",
        description="Analyze one image with services.vision and print a JSON summary.",
    )
    parser.add_argument("image", help="path to the frame (JPEG/PNG)")
    parser.add_argument("--max-side", type=int, default=None, help="analysis longest side (default 1280)")
    parser.add_argument("--detector", choices=("auto", "heuristic", "yolo", "none"), default=None)
    parser.add_argument("--model-path", default=None, help="YOLO weights path (default: $MEDCHECK_YOLO_MODEL)")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=None)
    parser.add_argument("--indent", type=int, default=2, help="JSON indent (0 = compact)")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    image_path = Path(args.image)
    hints = {
        "max_side": args.max_side,
        "detector": args.detector,
        "model_path": args.model_path,
        "device": args.device,
    }
    hints = {key: value for key, value in hints.items() if value is not None}

    try:
        image_bytes = image_path.read_bytes()
        result = analyze_frame(image_bytes, hints or None)
    except Exception as exc:  # noqa: BLE001 - the CLI reports any failure as JSON
        json.dump({"error": type(exc).__name__, "message": str(exc), "file": str(image_path)}, sys.stderr)
        sys.stderr.write("\n")
        return 1

    summary = build_summary(image_path, result)
    indent = args.indent if args.indent and args.indent > 0 else None
    print(json.dumps(summary, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
