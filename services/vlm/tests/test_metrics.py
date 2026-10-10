"""Tests for evaluation metrics."""
from __future__ import annotations

from services.vlm.eval.metrics import (
    ScoreBoard,
    latency_report,
    percentile,
    report_to_markdown,
    similarity,
    token_f1,
)


class TestSimilarity:
    def test_name_normalization(self):
        assert similarity("name", "Metformin  HCl", "metformin hcl") == 1.0
        assert similarity("name", "Metformin", "Metronidazole") == 0.0

    def test_strength_numeric(self):
        assert similarity("strength_value", 500, 500.0) == 1.0
        assert similarity("strength_value", "500", 500) == 1.0
        assert similarity("strength_value", 250, 500) == 0.0
        assert similarity("strength_value", "abc", 500) == 0.0

    def test_unit_aliases(self):
        assert similarity("strength_unit", "µg", "mcg") == 1.0
        assert similarity("strength_unit", "MG", "mg") == 1.0

    def test_missing_values(self):
        assert similarity("name", None, None) == 1.0
        assert similarity("name", None, "Metformin") == 0.0
        assert similarity("name", "Metformin", None) == 0.0

    def test_instructions_token_f1(self):
        assert similarity("instructions", "Take 1 tablet by mouth twice daily", "Take 1 tablet by mouth twice daily") == 1.0
        partial = similarity("instructions", "Take 1 tablet by mouth", "Take 1 tablet by mouth twice daily")
        assert 0.5 < partial < 1.0

    def test_token_f1_edges(self):
        assert token_f1("", "") == 1.0
        assert token_f1("a", "") == 0.0
        assert token_f1("a b", "b a") == 1.0


class TestScoreBoard:
    def truth(self):
        return {
            "name": {"value": "Metformin HCl"},
            "strength_value": {"value": 500},
            "strength_unit": {"value": "mg"},
            "form": {"value": "Tablet"},
            "manufacturer": {"value": "Acme Pharma"},
            "instructions": {"value": "Take 1 tablet by mouth twice daily"},
        }

    def test_perfect_predictions(self):
        board = ScoreBoard("perfect")
        board.add(self.truth(), self.truth())
        report = board.report()
        assert report["macro_f1"] == 1.0
        for field_name in report["fields"]:
            assert report["fields"][field_name]["f1"] == 1.0

    def test_wrong_name_counts_fp_and_fn(self):
        board = ScoreBoard("wrong")
        predicted = dict(self.truth(), name={"value": "Metronidazole"})
        board.add(predicted, self.truth())
        counts = board.report()["fields"]["name"]
        assert counts["tp"] == 0 and counts["fp"] == 1 and counts["fn"] == 1

    def test_missing_field_counts_fn(self):
        board = ScoreBoard("missing")
        predicted = {key: value for key, value in self.truth().items() if key != "strength_value"}
        board.add(predicted, self.truth())
        counts = board.report()["fields"]["strength_value"]
        assert counts["fn"] == 1 and counts["fp"] == 0

    def test_fabricated_field_counts_fp(self):
        board = ScoreBoard("fabricated")
        predicted = dict(self.truth(), manufacturer={"value": "Fake Pharma"})
        board.add(predicted, self.truth())
        counts = board.report()["fields"]["manufacturer"]
        assert counts["fp"] == 1 and counts["fn"] == 1


class TestLatency:
    def test_percentiles(self):
        assert percentile([10, 20, 30, 40], 50) == 25.0
        assert percentile([10, 20, 30, 40], 90) == 37.0
        assert percentile([], 50) is None

    def test_latency_report(self):
        assert latency_report([]) == {"n": 0, "p50": None, "p90": None, "mean": None}
        report = latency_report([100.0, 200.0])
        assert report["n"] == 2
        assert report["p50"] == 150.0


class TestMarkdown:
    def test_report_to_markdown_contains_modes_and_fields(self):
        from services.vlm.eval.run_eval import EvalRunner, EvalConfig  # noqa: PLC0415
        from services.vlm.eval.engines import GroundTruthOCR, TruthVLM
        from services.vlm.dataset import load_dataset
        from services.vlm.eval.run_eval import truth_by_sha

        samples = load_dataset()[:1]
        by_sha = truth_by_sha(samples)
        runner = EvalRunner(GroundTruthOCR(by_sha), TruthVLM(by_sha), EvalConfig())
        report = runner.run(samples)
        report["vram"] = {"before": "1, 2, 3", "after": "1, 4, 8"}
        markdown = report_to_markdown(report)
        assert "OCR-only F1" in markdown
        assert "macro F1" in markdown
        assert "nvidia-smi before" in markdown
