"""Shared fixtures for the vision test-suite."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def load_bytes():
    """Return a loader for committed synthetic fixture images."""

    def _load(name: str) -> bytes:
        path = FIXTURES_DIR / name
        assert path.is_file(), f"missing fixture {name!r}; run generate_fixtures.py"
        return path.read_bytes()

    return _load


@pytest.fixture(scope="session")
def labels() -> dict:
    return json.loads((FIXTURES_DIR / "labels.json").read_text())
