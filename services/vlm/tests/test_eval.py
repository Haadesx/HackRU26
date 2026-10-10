"""Tests for the OCR baseline engines and eval runner (no network)."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from services.vlm.dataset import load_dataset
from services.vlm.eval.engines import (
    GroundTruthOCR,
    OcrRead,
    TesseractOCR,
    TextLine,
    TruthVLM,
    parse_label_fields,
)
from services.vlm.eval.run_eval import EvalConfig, EvalRunner, load_env_file, truth_by_sha

CLEAN_LINES = [
    TextLine("SYNTHETIC LABEL — NOT FOR DISPENSING", 0.7),
    TextLine("MEDCHECK PHARMACY", 0.9),
    TextLine("Rx #: SYN-123456 SYNTHETIC PATIENT", 0.8),
    TextLine("Metformin HCl", 0.95),
    TextLine("500 mg", 0.93),
    TextLine("TABLET", 0.9),
    TextLine("TAKE:", 0.9),
    TextLine("Take 1 tablet by mouth twice daily", 0.88),
    TextLine("MFR: Acme Pharma", 0.9),
    TextLine("QTY: 30 REFILLS: 2", 0.8),
]


class TestParseLabelFields:
    def test_extracts_all_fields(self):
        fields = parse_label_fields(CLEAN_LINES)
        assert fields["name"]["value"] == "Metformin HCl"
        assert fields["strength_value"]["value"] == 500
        assert fields["strength_unit"]["value"] == "mg"
        assert fields["form"]["value"] == "Tablet"
        assert fields["manufacturer"]["value"] == "Acme Pharma"
        assert fields["instructions"]["value"] == "Take 1 tablet by mouth twice daily"
        assert all(entry["source"] == "ocr" for entry in fields.values())

    def test_confidence_comes_from_the_line(self):
        fields = parse_label_fields(CLEAN_LINES)
        assert fields["name"]["confidence"] == 0.95
        assert fields["strength_value"]["confidence"] == 0.93

    def test_multiline_instructions_stop_at_footer(self):
        lines = CLEAN_LINES[:7] + [
            TextLine("Take 1 capsule by mouth every", 0.8),
            TextLine("12 hours for 7 days", 0.8),
            TextLine("MFR: Bluepeak Labs", 0.9),
        ]
        fields = parse_label_fields(lines)
        assert fields["instructions"]["value"] == "Take 1 capsule by mouth every 12 hours for 7 days"

    def test_unit_normalization(self):
        lines = [TextLine("Levothyroxine Sodium", 0.9), TextLine("50 µg", 0.9)]
        fields = parse_label_fields(lines)
        assert fields["strength_unit"]["value"] == "mcg"

    def test_no_name_when_only_headers(self):
        fields = parse_label_fields([TextLine("MEDCHECK PHARMACY", 0.9), TextLine("Rx #: X", 0.8)])
        assert "name" not in fields


class TestGroundTruthControls:
    def test_ground_truth_ocr_lookup(self):
        samples = load_dataset()[:2]
        by_sha = truth_by_sha(samples)
        read = GroundTruthOCR(by_sha).read(samples[0].image_bytes())
        assert read.fields["name"]["value"] == samples[0].ground_truth["name"]
        assert read.fields["name"]["confidence"] == 1.0

    def test_unknown_image_yields_empty(self):
        read = GroundTruthOCR({}).read(b"\x89PNG\r\n\x1a\n" + b"x" * 10)
        assert read.fields == {}


class StubOCR:
    """OCR stub with controllable confidence, always correct values."""

    name = "stub"

    def __init__(self, truth: dict, confidence: float):
        self._truth = truth
        self._confidence = confidence

    def read(self, image_bytes: bytes) -> OcrRead:
        truth = self._truth[hashlib.sha256(image_bytes).hexdigest()]
        fields = {
            key: {"value": value, "confidence": self._confidence, "source": "ocr"}
            for key, value in truth.items()
        }
        return OcrRead(
            text=" ".join(str(value) for value in truth.values()),
            fields=fields,
            latency_ms=1.0,
            engine=self.name,
        )


class TestEvalRunner:
    def setup_method(self):
        self.samples = load_dataset()[:2]
        self.by_sha = truth_by_sha(self.samples)

    def test_confident_ocr_skips_vlm(self):
        runner = EvalRunner(GroundTruthOCR(self.by_sha), TruthVLM(self.by_sha), EvalConfig())
        report = runner.run(self.samples)
        assert report["vlm"]["calls"] == len(self.samples)  # vlm_only column only
        assert report["vlm"]["invocation_rate"] == 0.0
        assert report["modes"]["ocr_first_vlm"]["macro_f1"] == 1.0
        assert report["modes"]["ocr_only"]["macro_f1"] == 1.0

    def test_weak_ocr_escalates_and_reconciles(self):
        runner = EvalRunner(StubOCR(self.by_sha, 0.3), TruthVLM(self.by_sha), EvalConfig())
        report = runner.run(self.samples)
        assert report["vlm"]["invocation_rate"] == 1.0
        assert report["vlm"]["calls"] == 2 * len(self.samples)
        assert report["modes"]["ocr_first_vlm"]["macro_f1"] == 1.0

    def test_vlm_call_budget_is_enforced(self):
        runner = EvalRunner(StubOCR(self.by_sha, 0.3), TruthVLM(self.by_sha), EvalConfig(max_vlm_calls=1))
        with pytest.raises(RuntimeError, match="budget exceeded"):
            runner.run(self.samples)

    def test_condition_filter_and_limit(self):
        clean = [s for s in load_dataset() if s.condition == "clean"]
        by_sha = truth_by_sha(clean)
        runner = EvalRunner(GroundTruthOCR(by_sha), TruthVLM(by_sha), EvalConfig(conditions=["clean"]))
        report = runner.run(load_dataset())
        assert report["images"] == len(clean)
        assert report["modes"]["ocr_first_vlm"]["macro_f1"] == 1.0

    def test_cli_mock_roundtrip(self, tmp_path: Path):
        from services.vlm.eval.run_eval import main

        out = tmp_path / "results.json"
        code = main(["--mock", "--limit", "2", "--out", str(out), "--max-vlm-calls", "10"])
        assert code == 0
        assert out.exists()


class TestEnvFile:
    def test_load_env_file_filters_and_does_not_leak(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("MEDCHECK_VLM_BASE_URL", raising=False)
        env_file = tmp_path / "vllm.env"
        env_file.write_text(
            "# comment\nMEDCHECK_VLM_BASE_URL=http://rig:8100/v1\nOTHER_KEY=shhh\nMEDCHECK_VLM_MODEL='qwen'\n"
        )
        loaded = load_env_file(env_file)
        assert loaded == 2
        import os

        assert os.environ["MEDCHECK_VLM_BASE_URL"] == "http://rig:8100/v1"
        assert os.environ["MEDCHECK_VLM_MODEL"] == "qwen"
        assert "OTHER_KEY" not in os.environ


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract binary not installed")
class TestTesseractBaseline:
    def test_reads_clean_synthetic_label(self):
        sample = next(s for s in load_dataset() if s.condition == "clean")
        read = TesseractOCR().read(sample.image_bytes())
        assert read.error is None
        assert read.fields["strength_value"]["value"] == sample.ground_truth["strength_value"]
        assert "metformin" in read.fields["name"]["value"].lower()
