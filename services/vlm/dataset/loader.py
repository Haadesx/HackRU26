"""Load the synthetic labeled dataset and expose ground-truth fields."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

DATASET_DIR = Path(__file__).resolve().parent
MANIFEST_NAME = "ground_truth.json"

CANONICAL_FIELDS = (
    "name",
    "strength_value",
    "strength_unit",
    "form",
    "manufacturer",
    "instructions",
)


@dataclass(frozen=True)
class Sample:
    id: str
    image_path: Path
    condition: str
    ground_truth: Dict[str, Any]

    def image_bytes(self) -> bytes:
        return self.image_path.read_bytes()

    @property
    def truth_fields(self) -> Dict[str, Dict[str, Any]]:
        """Ground truth in canonical reconcile form (source ``ground_truth``)."""
        return {
            key: {"value": self.ground_truth[key], "confidence": 1.0, "source": "ground_truth"}
            for key in CANONICAL_FIELDS
            if self.ground_truth.get(key) is not None
        }


def load_dataset(root: Optional[Path] = None) -> List[Sample]:
    """Read the manifest and return samples; raises if the dataset is missing."""
    root = Path(root) if root else DATASET_DIR
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"{manifest_path} not found; run: python -m services.vlm.dataset.generate"
        )
    manifest = json.loads(manifest_path.read_text())
    samples: List[Sample] = []
    for entry in manifest["images"]:
        samples.append(
            Sample(
                id=entry["id"],
                image_path=root / entry["file"],
                condition=entry.get("condition", "clean"),
                ground_truth=entry["ground_truth"],
            )
        )
    return samples
