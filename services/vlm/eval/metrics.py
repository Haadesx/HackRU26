"""Per-field scoring and latency aggregation for the OCR-vs-VLM evaluation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

FIELDS = (
    "name",
    "strength_value",
    "strength_unit",
    "form",
    "manufacturer",
    "instructions",
)

# Instructions are free text: count as a hit when token F1 clears this bar.
INSTRUCTION_F1_THRESHOLD = 0.8

_UNIT_ALIASES = {"µg": "mcg", "ug": "mcg", "ug.": "mcg", "mgs": "mg", "gms": "g"}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value).lower().replace(",", " ").split()).strip(" .;:")


def _normalize_unit(value: Any) -> str:
    return _UNIT_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())


def token_f1(prediction: Any, truth: Any) -> float:
    """Multiset token F1 between two free-text values."""
    pred_tokens = _normalize_text(prediction).split()
    truth_tokens = _normalize_text(truth).split()
    if not pred_tokens and not truth_tokens:
        return 1.0
    if not pred_tokens or not truth_tokens:
        return 0.0
    remaining = list(truth_tokens)
    overlap = 0
    for token in pred_tokens:
        if token in remaining:
            remaining.remove(token)
            overlap += 1
    precision = overlap / len(pred_tokens)
    recall = overlap / len(truth_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def similarity(key: str, prediction: Any, truth: Any) -> float:
    """Score one field: 1.0 exact match, otherwise 0.0 (token F1 for instructions)."""
    if prediction is None or truth is None:
        return 1.0 if prediction is None and truth is None else 0.0
    if key == "strength_value":
        try:
            return 1.0 if float(prediction) == float(truth) else 0.0
        except (TypeError, ValueError):
            return 0.0
    if key == "strength_unit":
        return 1.0 if _normalize_unit(prediction) == _normalize_unit(truth) else 0.0
    if key == "instructions":
        return token_f1(prediction, truth)
    return 1.0 if _normalize_text(prediction) == _normalize_text(truth) else 0.0


class ScoreBoard:
    """Accumulates precision/recall counts for one evaluation mode."""

    def __init__(self, name: str):
        self.name = name
        self.samples = 0
        self.counts: Dict[str, Dict[str, int]] = {
            field: {"tp": 0, "fp": 0, "fn": 0, "truth_present": 0} for field in FIELDS
        }

    def add(self, predicted: Dict[str, Any], truth: Dict[str, Any]) -> None:
        self.samples += 1
        for key in FIELDS:
            truth_value = (truth.get(key) or {}).get("value")
            pred_value = (predicted.get(key) or {}).get("value")
            if truth_value is None and pred_value is None:
                continue
            if truth_value is not None:
                self.counts[key]["truth_present"] += 1
            score = similarity(key, pred_value, truth_value)
            hit = score >= (INSTRUCTION_F1_THRESHOLD if key == "instructions" else 0.999)
            if hit:
                self.counts[key]["tp"] += 1
            else:
                if pred_value is not None:
                    self.counts[key]["fp"] += 1
                if truth_value is not None:
                    self.counts[key]["fn"] += 1

    def report(self) -> Dict[str, Any]:
        per_field: Dict[str, Any] = {}
        f1s: List[float] = []
        for key, count in self.counts.items():
            tp, fp, fn = count["tp"], count["fp"], count["fn"]
            precision = tp / (tp + fp) if tp + fp else 0.0
            recall = tp / (tp + fn) if tp + fn else 0.0
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
            per_field[key] = {
                "precision": round(precision, 3),
                "recall": round(recall, 3),
                "f1": round(f1, 3),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "truth_present": count["truth_present"],
            }
            if count["truth_present"]:
                f1s.append(f1)
        return {
            "mode": self.name,
            "samples": self.samples,
            "fields": per_field,
            "macro_f1": round(sum(f1s) / len(f1s), 3) if f1s else 0.0,
        }


def percentile(values: List[float], p: float) -> Optional[float]:
    """Linear-interpolation percentile (p in 0..100); None for empty input."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    interpolated = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
    return round(interpolated, 1)


def latency_report(values: List[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"n": 0, "p50": None, "p90": None, "mean": None}
    return {
        "n": len(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "mean": round(sum(values) / len(values), 1),
    }


def report_to_markdown(report: Dict[str, Any]) -> str:
    """Render a results dict (from EvalRunner) as a markdown section."""
    lines: List[str] = []
    lines.append(f"### Evaluation results ({report.get('images', 0)} images)")
    lines.append("")
    lines.append("| Field | OCR-only F1 | VLM-only F1 | OCR-first + VLM-on-uncertainty F1 |")
    lines.append("|---|---|---|---|")
    modes = report.get("modes", {})
    for field_name in FIELDS:
        cells = [str(modes.get(mode, {}).get("fields", {}).get(field_name, {}).get("f1", "-")) for mode in
                 ("ocr_only", "vlm_only", "ocr_first_vlm")]
        lines.append(f"| {field_name} | " + " | ".join(cells) + " |")
    macro = [str(modes.get(mode, {}).get("macro_f1", "-")) for mode in ("ocr_only", "vlm_only", "ocr_first_vlm")]
    lines.append(f"| **macro F1** | **" + "** | **".join(macro) + "** |")
    lines.append("")
    latency = report.get("latency_ms", {})
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| OCR latency p50 / p90 | {latency.get('ocr', {}).get('p50')} / {latency.get('ocr', {}).get('p90')} ms |")
    lines.append(f"| VLM latency p50 / p90 | {latency.get('vlm', {}).get('p50')} / {latency.get('vlm', {}).get('p90')} ms |")
    lines.append(f"| VLM calls (budget {report.get('vlm', {}).get('budget')}) | {report.get('vlm', {}).get('calls')} |")
    lines.append(f"| OCR-first VLM invocation rate | {report.get('vlm', {}).get('invocation_rate')} |")
    vram = report.get("vram", {})
    if vram.get("before") or vram.get("after"):
        lines.append(f"| nvidia-smi before | `{vram.get('before')}` |")
        lines.append(f"| nvidia-smi after | `{vram.get('after')}` |")
    lines.append("")
    return "\n".join(lines)
