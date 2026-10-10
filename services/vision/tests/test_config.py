"""Configuration tests: MEDCHECK_YOLO_MODEL wiring and torch-free imports."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from services.vision.config import YOLO_MODEL_ENV, VisionConfig

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_model_path_defaults_to_none_when_env_unset(monkeypatch):
    monkeypatch.delenv(YOLO_MODEL_ENV, raising=False)
    assert VisionConfig().model_path is None
    assert VisionConfig.from_hints({}).model_path is None


def test_model_path_reads_env_var(monkeypatch):
    monkeypatch.setenv(YOLO_MODEL_ENV, "/opt/medcheck/yolo/bottle.pt")
    assert VisionConfig().model_path == "/opt/medcheck/yolo/bottle.pt"


def test_hints_override_env_model_path(monkeypatch):
    monkeypatch.setenv(YOLO_MODEL_ENV, "/env/weights.pt")
    config = VisionConfig.from_hints({"model_path": "/hint/weights.pt"})
    assert config.model_path == "/hint/weights.pt"


def test_explicit_heuristic_detector_ignores_env_model(monkeypatch):
    monkeypatch.setenv(YOLO_MODEL_ENV, "/env/weights.pt")
    config = VisionConfig.from_hints({"detector": "heuristic"})
    assert config.detector == "heuristic"
    assert config.model_path == "/env/weights.pt"  # recorded but unused by the heuristic


def test_package_import_never_imports_torch():
    """Mac must stay torch-free when MEDCHECK_YOLO_MODEL is unset."""
    env = dict(os.environ)
    env.pop(YOLO_MODEL_ENV, None)
    code = (
        "import sys\n"
        "assert 'torch' not in sys.modules, 'torch present before import'\n"
        "import services.vision\n"
        "assert 'torch' not in sys.modules, 'torch imported by services.vision'\n"
        "from services.vision import analyze_frame, crop_label, crop_label_array\n"
        "print('torch-free')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "torch-free" in completed.stdout
