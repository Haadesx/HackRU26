"""OCR-vs-VLM evaluation runner and CLI.

Compares three modes on the synthetic dataset:

* ``ocr_only``         — local OCR baseline alone;
* ``vlm_only``         — Qwen3-VL alone;
* ``ocr_first_vlm``    — OCR first, VLM only when ``should_use_vlm`` says so,
                         then fields reconciled with source attribution.

VLM calls are sequential and hard-capped (default 120) to respect the shared
GPU window. ``--ssh-host hermes-linux`` captures nvidia-smi before/after.

Usage:
    .venv/bin/python -m services.vlm.eval.run_eval --env-file ~/.medcheck/vllm.env \
        --ssh-host hermes-linux --out services/vlm/eval/results.json --md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from services.vlm.client import Qwen3VLClient, VlmResult
from services.vlm.dataset import Sample, load_dataset
from services.vlm.eval.engines import (
    GroundTruthOCR,
    OcrEngine,
    OcrUnavailable,
    TesseractOCR,
    TruthVLM,
)
from services.vlm.eval.metrics import ScoreBoard, latency_report, report_to_markdown
from services.vlm.reconcile import reconcile_fields, should_use_vlm, uncertainty_from_fields

MODES = ("ocr_only", "vlm_only", "ocr_first_vlm")


@dataclass
class EvalConfig:
    max_vlm_calls: int = 120
    min_field_confidence: float = 0.75
    conditions: Optional[Sequence[str]] = None


class EvalRunner:
    """Runs the three evaluation modes over a list of samples."""

    def __init__(self, ocr_engine: OcrEngine, vlm_client: Any, config: Optional[EvalConfig] = None):
        self.ocr_engine = ocr_engine
        self.vlm_client = vlm_client
        self.config = config or EvalConfig()
        self._vlm_calls = 0

    def _call_vlm(self, image_bytes: bytes, ocr_text: Optional[str]) -> VlmResult:
        if self._vlm_calls >= self.config.max_vlm_calls:
            raise RuntimeError(
                f"VLM call budget exceeded ({self.config.max_vlm_calls}); refusing further calls"
            )
        self._vlm_calls += 1
        return self.vlm_client.interpret(image_bytes, ocr_text=ocr_text)

    def run(self, samples: Sequence[Sample]) -> Dict[str, Any]:
        selected = [s for s in samples if self.config.conditions is None or s.condition in self.config.conditions]
        boards = {mode: ScoreBoard(mode) for mode in MODES}
        ocr_latencies: List[float] = []
        vlm_latencies: List[float] = []
        errors: List[str] = []
        gate_hits = 0
        conditions = Counter(s.condition for s in selected)
        reconcile_config = {"min_field_confidence": self.config.min_field_confidence}
        gate_config = {"min_field_confidence": self.config.min_field_confidence}

        for sample in selected:
            image = sample.image_bytes()
            truth = sample.truth_fields

            read = self.ocr_engine.read(image)
            ocr_latencies.append(read.latency_ms)
            if read.error:
                errors.append(f"{sample.id}: ocr: {read.error}")
            boards["ocr_only"].add(read.fields, truth)

            vlm_only = self._call_vlm(image, None)
            vlm_latencies.append(vlm_only.latency_ms)
            if vlm_only.error:
                errors.append(f"{sample.id}: vlm: {vlm_only.error}")
            boards["vlm_only"].add(vlm_only.fields, truth)

            uncertainty = uncertainty_from_fields(read.fields, config=reconcile_config)
            if should_use_vlm(uncertainty, config=gate_config):
                gate_hits += 1
                verified = self._call_vlm(image, read.text)
                vlm_latencies.append(verified.latency_ms)
                if verified.error:
                    errors.append(f"{sample.id}: vlm(ocr-first): {verified.error}")
                merged = reconcile_fields(read.fields, verified.fields, config=reconcile_config)
                boards["ocr_first_vlm"].add(merged.fields, truth)
            else:
                boards["ocr_first_vlm"].add(read.fields, truth)

        model = getattr(getattr(self.vlm_client, "config", None), "model", None) or getattr(
            self.vlm_client, "model", None
        )
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dataset": "medcheck-synthetic-labels",
            "images": len(selected),
            "conditions": dict(sorted(conditions.items())),
            "modes": {mode: boards[mode].report() for mode in MODES},
            "vlm": {
                "model": model,
                "calls": self._vlm_calls,
                "budget": self.config.max_vlm_calls,
                "invocation_rate": round(gate_hits / len(selected), 3) if selected else 0.0,
            },
            "latency_ms": {
                "ocr": latency_report(ocr_latencies),
                "vlm": latency_report(vlm_latencies),
            },
            "vram": {"before": None, "after": None},
            "errors": errors[:20],
        }


def capture_vram(ssh_host: Optional[str] = None, timeout: int = 25) -> str:
    """Return nvidia-smi memory lines locally or over ssh; never raises."""
    cmd = ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"]
    if ssh_host:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", ssh_host, *cmd]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:  # pragma: no cover - environment dependent
        return f"error: {type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return f"error: rc={proc.returncode} {proc.stderr.strip()[:200]}"
    return proc.stdout.strip()


def load_env_file(path: Path) -> int:
    """Load MEDCHECK_VLM_* keys from a KEY=VALUE file without echoing values."""
    loaded = 0
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.startswith("MEDCHECK_VLM_"):
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))
        loaded += 1
    return loaded


def truth_by_sha(samples: Sequence[Sample]) -> Dict[str, Dict[str, Any]]:
    return {hashlib.sha256(s.image_bytes()).hexdigest(): s.ground_truth for s in samples}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OCR-vs-VLM evaluation.")
    parser.add_argument("--dataset", type=Path, default=None, help="dataset root (default: services/vlm/dataset)")
    parser.add_argument("--limit", type=int, default=None, help="use only the first N images")
    parser.add_argument("--conditions", default=None, help="comma-separated condition filter, e.g. clean,blur")
    parser.add_argument("--max-vlm-calls", type=int, default=120)
    parser.add_argument("--out", type=Path, default=None, help="write full JSON results here")
    parser.add_argument("--md", action="store_true", help="print markdown table to stdout")
    parser.add_argument("--env-file", type=Path, default=None, help="load MEDCHECK_VLM_* keys from file")
    parser.add_argument("--mock", action="store_true", help="ground-truth OCR+VLM controls, no network")
    parser.add_argument("--ssh-host", default=None, help="capture nvidia-smi before/after on this host")
    args = parser.parse_args(argv)

    if args.env_file:
        loaded = load_env_file(args.env_file)
        print(f"loaded {loaded} MEDCHECK_VLM_* keys from {args.env_file}")

    samples = load_dataset(args.dataset)
    if args.limit:
        samples = samples[: args.limit]
    conditions = [c.strip() for c in args.conditions.split(",")] if args.conditions else None

    if args.mock:
        by_sha = truth_by_sha(samples)
        ocr_engine: OcrEngine = GroundTruthOCR(by_sha)
        vlm_client: Any = TruthVLM(by_sha)
    else:
        try:
            ocr_engine = TesseractOCR()
        except OcrUnavailable as exc:
            print(f"OCR baseline unavailable: {exc}")
            return 2
        vlm_client = Qwen3VLClient()

    runner = EvalRunner(
        ocr_engine,
        vlm_client,
        EvalConfig(max_vlm_calls=args.max_vlm_calls, conditions=conditions),
    )
    vram_before = capture_vram(args.ssh_host) if args.ssh_host else None
    report = runner.run(samples)
    if args.ssh_host:
        report["vram"] = {"before": vram_before, "after": capture_vram(args.ssh_host)}

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {args.out}")
    if args.md:
        print(report_to_markdown(report))
    else:
        macro = {mode: report["modes"][mode]["macro_f1"] for mode in MODES}
        print(f"images={report['images']} vlm_calls={report['vlm']['calls']} macro_f1={macro}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
