"""Shared pytest fixtures for the OCR service."""

from __future__ import annotations

import json
import pathlib

import pytest

SERVICE_DIR = pathlib.Path(__file__).resolve().parents[1]
FIXTURE_PATH = SERVICE_DIR / "fixtures" / "synthetic_labels.json"
ARTIFACT_PATHS = (
    SERVICE_DIR / "artifacts" / "accuracy_report.txt",
    SERVICE_DIR / "artifacts" / "ocr_e2e_report.txt",
)


@pytest.fixture(scope="session")
def synthetic_labels() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """Echo accuracy tables after the run (pytest captures prints by default)."""
    for path in ARTIFACT_PATHS:
        if not path.exists():
            continue
        terminalreporter.write_sep("=", f"MedCheck OCR report: {path.name}")
        terminalreporter.write_line(path.read_text(encoding="utf-8"))
