"""Field-level accuracy table on the synthetic labeled set (>= 20 lines).

The report is printed to the terminal at session end (see ``conftest.py``) and
written to ``services/ocr/artifacts/accuracy_report.txt``.
"""

from __future__ import annotations

import pathlib

from services.ocr.extract import extract_fields

SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]
ARTIFACT_PATH = SERVICE_DIR / "artifacts" / "accuracy_report.txt"


def _norm(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _fmt_strength(value: float | None, unit: str | None) -> str:
    if value is None or unit is None:
        return "-"
    number = int(value) if float(value).is_integer() else value
    return f"{number} {unit}"


def _metrics(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def test_field_level_accuracy(synthetic_labels):
    labels = synthetic_labels["labels"]
    assert len(labels) >= 20, "synthetic set must contain at least 20 labeled lines"

    counters = {field: {"tp": 0, "fp": 0, "fn": 0} for field in ("name", "strength", "form")}
    instruction_total = 0
    instruction_hits = 0
    rows: list[str] = []

    for entry in labels:
        raw = "\n".join(entry["lines"])
        expect = entry["expect"]
        extraction = extract_fields(raw)

        predicted_name = extraction.name.value
        name_ok = predicted_name is not None and _norm(predicted_name) == _norm(expect["name"])
        strength_ok = (
            extraction.strength.value == expect["strength_value"]
            and extraction.strength.unit == expect["strength_unit"]
        )
        form_ok = extraction.form.value == expect["form"]

        if predicted_name is None:
            counters["name"]["fn"] += 1
        elif name_ok:
            counters["name"]["tp"] += 1
        else:
            counters["name"]["fp"] += 1
            counters["name"]["fn"] += 1

        if extraction.strength.value is None:
            counters["strength"]["fn"] += 1
        elif strength_ok:
            counters["strength"]["tp"] += 1
        else:
            counters["strength"]["fp"] += 1
            counters["strength"]["fn"] += 1

        if extraction.form.value is None:
            counters["form"]["fn"] += 1
        elif form_ok:
            counters["form"]["tp"] += 1
        else:
            counters["form"]["fp"] += 1
            counters["form"]["fn"] += 1

        kinds = {item.kind for item in extraction.instructions}
        expected_kinds = entry.get("expect_kinds")
        if expected_kinds:
            instruction_total += 1
            if set(expected_kinds) <= kinds:
                instruction_hits += 1

        ok = name_ok and strength_ok and form_ok
        rows.append(
            f"{entry['id']:<4} "
            f"{predicted_name or '-'} | {expect['name']:<22.22} "
            f"{_fmt_strength(extraction.strength.value, extraction.strength.unit) or '-':>8} | "
            f"{_fmt_strength(expect['strength_value'], expect['strength_unit']):>8} "
            f"{extraction.form.value or '-':>8} | {expect['form']:<8} "
            f"{'ok' if ok else 'FAIL'}"
        )

    summary_lines = []
    for field in ("name", "strength", "form"):
        metrics = _metrics(**counters[field])
        summary_lines.append(
            f"{field:<9} tp={counters[field]['tp']:>3} fp={counters[field]['fp']:>2} fn={counters[field]['fn']:>2} "
            f"precision={metrics['precision']:.3f} recall={metrics['recall']:.3f} f1={metrics['f1']:.3f}"
        )

    report = "\n".join(
        [
            "MedCheck OCR — field-level accuracy on synthetic labels",
            "dataset: services/ocr/fixtures/synthetic_labels.json",
            f"labels: {len(labels)} | layer: text extraction (services/ocr/extract.py)",
            "",
            "id   name(pred | exp)                strength(pred | exp)   form(pred | exp)         result",
            "-" * 96,
            *rows,
            "-" * 96,
            *summary_lines,
            f"instructions(kind coverage): {instruction_hits}/{instruction_total} entries satisfied",
        ]
    )
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)

    name_metrics = _metrics(**counters["name"])
    strength_metrics = _metrics(**counters["strength"])
    form_metrics = _metrics(**counters["form"])
    assert name_metrics["precision"] >= 0.95 and name_metrics["recall"] >= 0.95
    assert strength_metrics["precision"] >= 0.95 and strength_metrics["recall"] >= 0.95
    assert form_metrics["precision"] >= 0.9 and form_metrics["recall"] >= 0.9
    assert instruction_total > 0 and instruction_hits == instruction_total
