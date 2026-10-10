#!/usr/bin/env python3
"""Validate contracts/examples against contracts/v1 schemas and pydantic models.

Usage: .venv/bin/python scripts/validate_contract.py
Exit 0 = all good.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.common.contract import ScanResponse  # noqa: E402

SCHEMA = json.loads((ROOT / "contracts/v1/scan_response.schema.json").read_text())
EXAMPLES = sorted((ROOT / "contracts/examples").glob("*_response.json"))


def main() -> int:
    failures = 0
    for path in EXAMPLES:
        data = json.loads(path.read_text())
        try:
            jsonschema.validate(data, SCHEMA)
        except jsonschema.ValidationError as exc:
            print(f"FAIL schema  {path.name}: {exc.message}")
            failures += 1
            continue
        try:
            ScanResponse.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL pydantic {path.name}: {exc}")
            failures += 1
            continue
        print(f"OK   {path.name} (status={data['status']}, mode={data['mode']})")
    print(f"{len(EXAMPLES) - failures}/{len(EXAMPLES)} examples valid")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
