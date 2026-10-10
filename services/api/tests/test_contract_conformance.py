"""Contract conformance tests: JSON Schema, examples, and mock determinism."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from services.api.fixtures import FIXTURES
from services.api.pipeline import (
    MockPipeline,
    ScanContext,
    build_fixture_response,
    request_key,
    to_contract_json,
)
from services.common.contract import ScanResponse

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "contracts" / "v1" / "scan_response.schema.json"
EXAMPLES_DIR = REPO_ROOT / "contracts" / "examples"

SCHEMA = json.loads(SCHEMA_PATH.read_text())
EXAMPLE_PATHS = sorted(EXAMPLES_DIR.glob("*.json"))


def _ids(paths):
    return [path.name for path in paths]


def test_schema_is_valid_draft7():
    jsonschema.Draft7Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("example_path", EXAMPLE_PATHS, ids=_ids(EXAMPLE_PATHS))
def test_examples_validate_against_json_schema(example_path: Path):
    instance = json.loads(example_path.read_text())
    jsonschema.validate(instance=instance, schema=SCHEMA)


@pytest.mark.parametrize("example_path", EXAMPLE_PATHS, ids=_ids(EXAMPLE_PATHS))
def test_examples_validate_against_pydantic_mirror(example_path: Path):
    instance = json.loads(example_path.read_text())
    parsed = ScanResponse.model_validate(instance)
    assert parsed.contract_version == "1.1.0"


@pytest.mark.parametrize("example_path", EXAMPLE_PATHS, ids=_ids(EXAMPLE_PATHS))
def test_examples_survive_outbound_serialization(example_path: Path):
    instance = json.loads(example_path.read_text())
    payload = to_contract_json(ScanResponse.model_validate(instance))
    jsonschema.validate(instance=payload, schema=SCHEMA)


@pytest.mark.parametrize("fixture", FIXTURES, ids=[f["key"] for f in FIXTURES])
def test_mock_fixture_responses_validate_against_json_schema(fixture):
    response = build_fixture_response(fixture, "req-conformance00", 1.0)
    payload = to_contract_json(response)
    jsonschema.validate(instance=payload, schema=SCHEMA)
    assert payload["mode"] == "mock"


def test_required_nullable_keys_survive_serialization():
    blurry = next(f for f in FIXTURES if f["key"] == "blurry_rescan")
    payload = to_contract_json(build_fixture_response(blurry, "req-conformance00", 1.0))
    assert "value" in payload["medication"]["name"]
    assert payload["medication"]["name"]["value"] is None


def test_nullable_dose_keys_survive_serialization():
    from services.common.contract import DoseInfo

    response = build_fixture_response(FIXTURES[0], "req-conformance00", 1.0)
    response.instructions.dose = DoseInfo()  # quantity/unit unknown
    payload = to_contract_json(response)
    assert payload["instructions"]["dose"]["quantity"] is None
    assert payload["instructions"]["dose"]["unit"] is None
    assert payload["instructions"]["dose"]["source"] == "none"
    jsonschema.validate(instance=payload, schema=SCHEMA)


@pytest.mark.parametrize(
    "fixture",
    [f for f in FIXTURES if f["instructions"].get("dose") is not None],
    ids=[f["key"] for f in FIXTURES if f["instructions"].get("dose") is not None],
)
def test_mock_fixtures_carry_v11_dose(fixture):
    payload = to_contract_json(build_fixture_response(fixture, "req-dose00000000", 1.0))
    dose = payload["instructions"]["dose"]
    assert dose["quantity"] > 0
    assert dose["unit"]
    assert dose["confidence"] >= 0.5
    assert dose["source"] == "ocr"


def test_mock_pipeline_is_deterministic():
    pipeline = MockPipeline()
    ctx = ScanContext(
        request_id="req-determinism0",
        image=b"\x89PNG\r\n\x1a\n-deterministic",
        content_type="image/png",
        client="test",
        requested_mode="mock",
        hints={"locale": "en-US"},
    )
    first = asyncio.run(pipeline.scan(ctx))
    second = asyncio.run(pipeline.scan(ctx))
    assert first.model_dump(exclude={"request_id", "timing"}) == second.model_dump(
        exclude={"request_id", "timing"}
    )
    assert first.mode == "mock"


def test_request_key_changes_with_inputs():
    base = request_key(b"\x89PNG\r\n\x1a\na", "test", None)
    assert base != request_key(b"\x89PNG\r\n\x1a\nb", "test", None)
    assert base != request_key(b"\x89PNG\r\n\x1a\na", "ios", None)
    assert base != request_key(b"\x89PNG\r\n\x1a\na", "test", {"locale": "en-US"})


def test_mock_never_fabricates_medication_names():
    allowed = {
        fixture["medication"]["name"]["value"]
        for fixture in FIXTURES
        if fixture["medication"]["name"]["value"] is not None
    }
    for fixture in FIXTURES:
        response = build_fixture_response(fixture, "req-namesafe0000", 0.0)
        if response.medication.name.value is not None:
            assert response.medication.name.value in allowed
        for candidate in response.candidates:
            assert candidate.name in allowed
