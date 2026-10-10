"""Tests for the synthetic dataset generator and loader."""
from __future__ import annotations

import json

from services.vlm.dataset import CANONICAL_FIELDS, load_dataset
from services.vlm.dataset.generate import build_dataset
from services.vlm.dataset.loader import DATASET_DIR


def test_dataset_size_and_files_exist():
    samples = load_dataset()
    assert len(samples) >= 12
    assert [s.image_path.exists() for s in samples] == [True] * len(samples)


def test_ground_truth_is_complete():
    for sample in load_dataset():
        for key in CANONICAL_FIELDS:
            assert sample.ground_truth.get(key) is not None, f"{sample.id} missing {key}"
        assert sample.ground_truth["strength_unit"] in ("mg", "mcg")


def test_conditions_cover_clean_and_degraded():
    conditions = {s.condition for s in load_dataset()}
    assert {"clean", "blur", "dark", "glare", "tilt", "small_text", "low_contrast"} <= conditions


def test_truth_fields_shape():
    sample = load_dataset()[0]
    fields = sample.truth_fields
    assert set(fields) == set(CANONICAL_FIELDS)
    assert all(entry["confidence"] == 1.0 for entry in fields.values())
    assert all(entry["source"] == "ground_truth" for entry in fields.values())


def test_regeneration_is_deterministic(tmp_path):
    rebuilt = build_dataset(tmp_path, seed=1337)
    committed = json.loads((DATASET_DIR / "ground_truth.json").read_text())
    assert rebuilt["count"] == committed["count"]
    assert [entry["sha256"] for entry in rebuilt["images"]] == [
        entry["sha256"] for entry in committed["images"]
    ]
