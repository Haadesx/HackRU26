"""Bounded GPU benchmark for the existing Qwen3-VL vLLM service.

Never launches a model process. Sequential requests only. Requires an explicit
orchestrator GPU window: pass ``--confirm-gpu-window`` or set
``MEDCHECK_GPU_WINDOW_OK=1``. Captures nvidia-smi before/after.

Usage:
    MEDCHECK_GPU_WINDOW_OK=1 .venv/bin/python -m services.vlm.benchmarks.gpu_bench \
        --env-file ~/.medcheck/vllm.env --ssh-host hermes-linux --images 12 \
        --out services/vlm/benchmarks/results.json
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.vlm.client import Qwen3VLClient
from services.vlm.dataset import load_dataset
from services.vlm.eval.metrics import latency_report
from services.vlm.eval.run_eval import capture_vram, load_env_file

MAX_IMAGES = 60  # stay well inside the shared-GPU budget


def run_benchmark(
    client: Qwen3VLClient,
    image_payloads: List[bytes],
    ssh_host: Optional[str] = None,
) -> Dict[str, Any]:
    latencies: List[float] = []
    errors: List[str] = []
    vram_before = capture_vram(ssh_host)
    started = time.perf_counter()

    for index, image in enumerate(image_payloads):
        result = client.interpret(image, ocr_text=None)
        latencies.append(result.latency_ms)
        if result.error:
            errors.append(f"image {index}: {result.error}")

    wall_s = time.perf_counter() - started
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": client.config.model,
        "endpoint": client.config.base_url,
        "images": len(image_payloads),
        "sequential": True,
        "latency_ms": latency_report(latencies),
        "wall_s": round(wall_s, 2),
        "images_per_sec": round(len(image_payloads) / wall_s, 2) if wall_s > 0 else None,
        "vram": {"before": vram_before, "after": capture_vram(ssh_host)},
        "errors": errors[:10],
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Sequential GPU latency benchmark (bounded).")
    parser.add_argument("--confirm-gpu-window", action="store_true", help="assert orchestrator grant")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--images", type=int, default=12)
    parser.add_argument("--ssh-host", default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if not args.confirm_gpu_window and os.environ.get("MEDCHECK_GPU_WINDOW_OK") != "1":
        print("Refusing to benchmark: no GPU window confirmed (orchestrator grant required).")
        return 2

    if args.env_file:
        loaded = load_env_file(args.env_file)
        print(f"loaded {loaded} MEDCHECK_VLM_* keys")

    samples = load_dataset()
    limit = max(1, min(args.images, MAX_IMAGES, len(samples)))
    payloads = [sample.image_bytes() for sample in samples[:limit]]

    with Qwen3VLClient() as client:
        report = run_benchmark(client, payloads, ssh_host=args.ssh_host)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {args.out}")
    print(
        f"images={report['images']} p50={report['latency_ms']['p50']}ms "
        f"p90={report['latency_ms']['p90']}ms images/s={report['images_per_sec']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
