"""Tests for the uncertainty/reconciliation helper."""
from __future__ import annotations

from services.vlm.reconcile import (
    ReconcileResult,
    instructions_raw,
    reconcile_fields,
    should_use_vlm,
    to_contract_medication,
    uncertainty_from_fields,
)


def field(value, confidence=0.9, source="ocr"):
    return {"value": value, "confidence": confidence, "source": source}


class TestShouldUseVlm:
    def test_high_always(self):
        assert should_use_vlm({"level": "high", "rescan_required": False}) is True

    def test_medium_always(self):
        assert should_use_vlm({"level": "medium", "rescan_required": False}) is True

    def test_low_confident_fields_no(self):
        uncertainty = {
            "level": "low",
            "rescan_required": False,
            "fields": {"name": {"confidence": 0.95}, "strength_value": {"confidence": 0.9}},
        }
        assert should_use_vlm(uncertainty) is False

    def test_low_weak_critical_field_yes(self):
        uncertainty = {
            "level": "low",
            "rescan_required": False,
            "fields": {"name": {"confidence": 0.4}, "strength_value": {"confidence": 0.9}},
        }
        assert should_use_vlm(uncertainty) is True

    def test_low_missing_critical_field_yes(self):
        assert should_use_vlm({"level": "low", "rescan_required": False, "fields": {}}) is True

    def test_rescan_beats_vlm(self):
        assert should_use_vlm({"level": "high", "rescan_required": True}) is False

    def test_rescan_override(self):
        assert (
            should_use_vlm({"level": "high", "rescan_required": True}, config={"invoke_on_rescan": True})
            is True
        )

    def test_missing_level_escalates(self):
        assert should_use_vlm({}) is True

    def test_non_critical_weak_field_no(self):
        uncertainty = {
            "level": "low",
            "rescan_required": False,
            "fields": {
                "name": {"confidence": 0.9},
                "strength_value": {"confidence": 0.9},
                "manufacturer": {"confidence": 0.1},
            },
        }
        assert should_use_vlm(uncertainty) is False

    def test_custom_critical_fields(self):
        uncertainty = {
            "level": "low",
            "rescan_required": False,
            "fields": {
                "name": {"confidence": 0.95},
                "strength_value": {"confidence": 0.9},
                "manufacturer": {"confidence": 0.1},
            },
        }
        assert should_use_vlm(uncertainty) is False
        assert should_use_vlm(uncertainty, config={"critical_fields": ("manufacturer",)}) is True


class TestReconcileFields:
    def test_ocr_only(self):
        result = reconcile_fields({"name": field("Metformin")}, {})
        assert result.used_vlm is False
        assert result.fields["name"] == {"value": "Metformin", "confidence": 0.9, "source": "ocr"}

    def test_vlm_only(self):
        result = reconcile_fields({}, {"name": field("Metformin", 0.8, "vlm")})
        assert result.fields["name"]["source"] == "vlm"

    def test_agreement_keeps_ocr_boosts_confidence(self):
        result = reconcile_fields(
            {"name": field("Metformin", 0.6)},
            {"name": field("metformin", 0.9, "vlm")},
        )
        assert result.fields["name"] == {"value": "Metformin", "confidence": 0.9, "source": "ocr"}
        assert result.conflicts == []

    def test_disagreement_ocr_wins_without_margin(self):
        result = reconcile_fields(
            {"name": field("Metformin", 0.9)},
            {"name": field("Metronidazole", 0.8, "vlm")},
        )
        assert result.fields["name"]["value"] == "Metformin"
        assert result.fields["name"]["source"] == "ocr"
        assert len(result.conflicts) == 1
        assert result.conflicts[0].chosen_source == "ocr"

    def test_disagreement_vlm_wins_with_margin(self):
        result = reconcile_fields(
            {"name": field("Metformln", 0.5)},
            {"name": field("Metformin", 0.95, "vlm")},
        )
        assert result.fields["name"]["value"] == "Metformin"
        assert result.fields["name"]["source"] == "vlm"
        assert "ocr_vlm_conflict:name" in result.conflict_reasons()[0]

    def test_partial_merge(self):
        result = reconcile_fields(
            {"name": field("Lisinopril"), "strength_value": field(10)},
            {"strength_unit": field("mg", 0.9, "vlm"), "form": field("Tablet", 0.8, "vlm")},
        )
        assert result.fields["strength_value"]["source"] == "ocr"
        assert result.fields["strength_unit"]["source"] == "vlm"
        assert result.fields["form"]["source"] == "vlm"

    def test_ignores_null_values(self):
        result = reconcile_fields({"name": {"value": None, "confidence": 0.1, "source": "ocr"}}, {})
        assert result.fields == {}

    def test_deterministic_key_order(self):
        result = reconcile_fields({"strength_unit": field("mg")}, {"form": field("Tablet", 0.8, "vlm")})
        assert list(result.fields) == ["form", "strength_unit"]


class TestContractMapping:
    def test_full_mapping(self):
        result = reconcile_fields(
            {
                "name": field("Metformin HCl", 0.9),
                "strength_value": field(500, 0.85),
                "strength_unit": field("mg", 0.85),
                "form": field("Tablet", 0.8),
                "manufacturer": field("Acme Pharma", 0.7),
                "instructions": field("Take 1 tablet by mouth twice daily", 0.9),
            },
            {},
        )
        medication = to_contract_medication(result.fields)
        assert medication["name"] == {"value": "Metformin HCl", "confidence": 0.9, "source": "ocr"}
        assert medication["strength"] == {
            "value": 500,
            "unit": "mg",
            "confidence": 0.85,
            "source": "ocr",
        }
        assert medication["form"]["value"] == "Tablet"
        assert medication["manufacturer"]["value"] == "Acme Pharma"
        assert instructions_raw(result.fields) == "Take 1 tablet by mouth twice daily"

    def test_missing_name_is_none_source(self):
        medication = to_contract_medication({})
        assert medication["name"] == {"value": None, "confidence": 0.0, "source": "none"}
        assert "strength" not in medication
        assert instructions_raw({}) is None

    def test_strength_without_unit(self):
        medication = to_contract_medication({"strength_value": field(5, 0.6)})
        assert medication["strength"]["value"] == 5
        assert medication["strength"]["unit"] is None


class TestUncertaintyFromFields:
    def confident_fields(self):
        return {
            "name": field("Metformin HCl", 0.95),
            "strength_value": field(500, 0.92),
            "strength_unit": field("mg", 0.92),
            "form": field("Tablet", 0.9),
            "manufacturer": field("Acme Pharma", 0.85),
            "instructions": field("Take 1 tablet by mouth twice daily", 0.9),
        }

    def test_all_confident_is_low(self):
        uncertainty = uncertainty_from_fields(self.confident_fields())
        assert uncertainty["level"] == "low"
        assert uncertainty["reasons"] == []
        assert uncertainty["rescan_required"] is False

    def test_missing_critical_is_high(self):
        fields = self.confident_fields()
        del fields["name"]
        uncertainty = uncertainty_from_fields(fields)
        assert uncertainty["level"] == "high"
        assert "missing:name" in uncertainty["reasons"]
        assert should_use_vlm(uncertainty) is True

    def test_weak_critical_is_high(self):
        fields = self.confident_fields()
        fields["strength_value"] = field(500, 0.2)
        uncertainty = uncertainty_from_fields(fields)
        assert uncertainty["level"] == "high"
        assert any(reason.startswith("low_confidence:strength_value") for reason in uncertainty["reasons"])

    def test_weak_noncritical_is_medium(self):
        fields = self.confident_fields()
        fields["manufacturer"] = field("Acme Pharma", 0.3)
        uncertainty = uncertainty_from_fields(fields)
        assert uncertainty["level"] == "medium"
        assert uncertainty["fields"]["manufacturer"]["confidence"] == 0.3

    def test_rescan_never_set_here(self):
        uncertainty = uncertainty_from_fields({})
        assert uncertainty["level"] == "high"
        assert uncertainty["rescan_required"] is False
