"""Tests for the gated GPU benchmark entry point (no network, no GPU)."""
from __future__ import annotations

from services.vlm.benchmarks.gpu_bench import main


def test_benchmark_requires_gpu_window(monkeypatch):
    monkeypatch.delenv("MEDCHECK_GPU_WINDOW_OK", raising=False)
    assert main(["--images", "1"]) == 2
