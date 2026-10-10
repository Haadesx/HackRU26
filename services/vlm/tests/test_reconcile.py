"""Tests for the uncertainty/reconciliation helper."""
from __future__ import annotations

from services.vlm.reconcile import (
    ReconcileResult,
    instructions_raw,
    reconcile_fields,
    should_use_vlm,
    should_use_vlm_multi,
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

    # -- Milestone 2 triggers -------------------------------------------------

    def low_uncertainty(self, **overrides):
        base = {
            "level": "low",
            "rescan_required": False,
            "fields": {
                "name": {"confidence": 0.87},
                "strength_value": {"confidence": 0.92},
                "strength_unit": {"confidence": 0.92},
                "form": {"confidence": 0.9},
                "manufacturer": {"confidence": 0.88},
                "instructions": {"confidence": 0.9},
            },
        }
        base.update(overrides)
        return base

    def test_candidate_mismatch_escalates_confidence_blind_case(self):
        """Measured img_001: OCR read "Metformin HCI" at 0.87 — confident but wrong."""
        uncertainty = self.low_uncertainty()
        assert uncertainty["fields"]["name"]["confidence"] == 0.87
        assert should_use_vlm(uncertainty) is False  # confidence alone misses it
        assert should_use_vlm(uncertainty, config={"candidate_mismatch": True}) is True

    def test_candidate_mismatch_from_uncertainty_payload(self):
        assert should_use_vlm(self.low_uncertainty(candidate_mismatch=True)) is True

    def test_candidate_mismatch_defaults_off(self):
        assert should_use_vlm(self.low_uncertainty(), config={"candidate_mismatch": False}) is False

    def test_rescan_still_beats_candidate_mismatch(self):
        uncertainty = self.low_uncertainty(rescan_required=True, candidate_mismatch=True)
        assert should_use_vlm(uncertainty) is False
        assert should_use_vlm(uncertainty, config={"candidate_mismatch": True}) is False

    def test_min_frame_score_escalates(self):
        assert should_use_vlm(self.low_uncertainty(frame_score=0.3)) is False  # disabled by default
        assert should_use_vlm(self.low_uncertainty(frame_score=0.3), config={"min_frame_score": 0.45}) is True
        assert should_use_vlm(self.low_uncertainty(frame_score=0.8), config={"min_frame_score": 0.45}) is False

    def test_min_frame_score_accepts_nested_frame_quality(self):
        uncertainty = self.low_uncertainty(frame_quality={"score": 0.2})
        assert should_use_vlm(uncertainty, config={"min_frame_score": 0.45}) is True

    def test_min_frame_score_ignored_when_score_missing(self):
        assert should_use_vlm(self.low_uncertainty(), config={"min_frame_score": 0.45}) is False

    def test_min_field_confidence_is_tunable(self):
        uncertainty = self.low_uncertainty(fields={"name": {"confidence": 0.8}, "strength_value": {"confidence": 0.9}})
        assert should_use_vlm(uncertainty) is False
        assert should_use_vlm(uncertainty, config={"min_field_confidence": 0.9}) is True

    def test_missing_optional_fields_do_not_escalate(self):
        """Apollo M3 regression: sharp label, manufacturer missing, still no VLM."""
        fields = {
            "name": field("Metformin HCl", 0.95),
            "strength_value": field(500, 0.9),
            "strength_unit": field("mg", 0.9),
            "form": field("Tablet", 0.75),
            "instructions": field("Take 1 tablet by mouth twice daily", 0.9),
            # manufacturer missing on purpose
        }
        uncertainty = uncertainty_from_fields(fields)
        assert uncertainty["level"] == "medium"  # optional field missing
        assert should_use_vlm(uncertainty) is False

    def test_medium_level_with_confident_escalation_fields_does_not_escalate(self):
        uncertainty = {
            "level": "medium",
            "rescan_required": False,
            "fields": {"name": {"confidence": 0.9}, "strength_value": {"confidence": 0.9}},
        }
        assert should_use_vlm(uncertainty) is False

    def test_escalation_fields_is_configurable(self):
        uncertainty = self.low_uncertainty(
            fields={
                "name": {"confidence": 0.3},
                "strength_value": {"confidence": 0.9},
                "form": {"confidence": 0.95},
            }
        )
        assert should_use_vlm(uncertainty) is True  # name is an escalation field
        assert should_use_vlm(uncertainty, config={"escalation_fields": ("form",)}) is False
        assert should_use_vlm(uncertainty, config={"escalation_fields": ("strength_value",)}) is False

    def test_critical_fields_alias_still_resolves(self):
        uncertainty = {
            "level": "low",
            "rescan_required": False,
            "fields": {"name": {"confidence": 0.9}, "strength_value": {"confidence": 0.9},
                       "form": {"confidence": 0.5}},
        }
        assert should_use_vlm(uncertainty) is False
        assert should_use_vlm(uncertainty, config={"critical_fields": ("form",)}) is True


class TestShouldUseVlmMulti:
    """Multi-frame gate: fusion conflicts escalate; otherwise single-frame rules."""

    def confident(self):
        return {
            "level": "low",
            "rescan_required": False,
            "fields": {
                "name": {"confidence": 0.95},
                "strength_value": {"confidence": 0.9},
            },
        }

    def test_fusion_conflicts_bool_escalates(self):
        uncertainty = self.confident()
        uncertainty["fusion_conflicts"] = True
        assert should_use_vlm_multi(uncertainty) is True
        assert should_use_vlm(uncertainty) is False  # single-frame gate unchanged

    def test_fusion_conflicts_list_escalates(self):
        uncertainty = self.confident()
        uncertainty["fusion_conflicts"] = ["name"]
        assert should_use_vlm_multi(uncertainty) is True

    def test_fusion_conflicts_runtime_signal_in_config(self):
        assert should_use_vlm_multi(self.confident(), config={"fusion_conflicts": True}) is True

    def test_empty_conflict_list_does_not_escalate(self):
        uncertainty = self.confident()
        uncertainty["fusion_conflicts"] = []
        assert should_use_vlm_multi(uncertainty) is False

    def test_rescan_beats_fusion_conflicts(self):
        uncertainty = self.confident()
        uncertainty.update({"fusion_conflicts": True, "rescan_required": True})
        assert should_use_vlm_multi(uncertainty) is False
        assert should_use_vlm_multi(uncertainty, config={"invoke_on_rescan": True}) is True

    def test_weak_identity_still_escalates(self):
        uncertainty = {
            "level": "low",
            "rescan_required": False,
            "fields": {"name": {"confidence": 0.3}, "strength_value": {"confidence": 0.9}},
        }
        assert should_use_vlm_multi(uncertainty) is True

    def test_candidate_mismatch_still_escalates(self):
        assert should_use_vlm_multi(self.confident(), config={"candidate_mismatch": True}) is True

    def test_high_level_still_escalates(self):
        assert should_use_vlm_multi({"level": "high", "rescan_required": False}) is True

    def test_matches_single_gate_without_fusion(self):
        cases = [
            self.confident(),
            {"level": "high", "rescan_required": False},
            {
                "level": "medium",
                "rescan_required": False,
                "fields": {"name": {"confidence": 0.9}, "strength_value": {"confidence": 0.9}},
            },
            {"level": "low", "rescan_required": False, "fields": {}},
            {"level": "low", "rescan_required": True},
        ]
        for uncertainty in cases:
            assert should_use_vlm_multi(uncertainty) is should_use_vlm(uncertainty)


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


class TestReconcileNormalization:
    """Case/whitespace/unit-form noise must not be reported as conflicts."""

    def test_form_plural_not_conflict(self):
        result = reconcile_fields(
            {"form": field("Tablet", 0.9)},
            {"form": field("TABLETS", 0.8, "vlm")},
        )
        assert result.conflicts == []
        assert result.fields["form"]["value"] == "Tablet"

    def test_name_case_whitespace_not_conflict(self):
        result = reconcile_fields(
            {"name": field("Metformin  HCl", 0.9)},
            {"name": field("metformin hcl", 0.8, "vlm")},
        )
        assert result.conflicts == []

    def test_salt_suffix_not_conflict_keeps_more_specific(self):
        result = reconcile_fields(
            {"name": field("Metformin", 0.9)},
            {"name": field("METFORMIN HCl", 0.85, "vlm")},
        )
        assert result.conflicts == []
        assert result.fields["name"] == {
            "value": "METFORMIN HCl",
            "confidence": 0.9,
            "source": "vlm",
        }

    def test_manufacturer_suffix_not_conflict(self):
        result = reconcile_fields(
            {"manufacturer": field("Acme", 0.8)},
            {"manufacturer": field("Acme Pharma", 0.7, "vlm")},
        )
        assert result.conflicts == []
        assert result.fields["manufacturer"]["value"] == "Acme Pharma"

    def test_unit_alias_not_conflict(self):
        result = reconcile_fields(
            {"strength_unit": field("µg", 0.9)},
            {"strength_unit": field("MCG", 0.8, "vlm")},
        )
        assert result.conflicts == []

    def test_strength_number_and_spacing_not_conflict(self):
        result = reconcile_fields(
            {"strength_value": field(500, 0.9), "strength_unit": field("mg", 0.9)},
            {"strength_value": field(500.0, 0.8, "vlm"), "strength_unit": field(" MG ", 0.8, "vlm")},
        )
        assert result.conflicts == []

    def test_instructions_whitespace_not_conflict(self):
        result = reconcile_fields(
            {"instructions": field("Take 1 tablet by mouth twice daily", 0.9)},
            {"instructions": field("  Take 1 tablet by mouth twice daily. ", 0.8, "vlm")},
        )
        assert result.conflicts == []

    def test_instructions_real_difference_is_conflict_with_both_values(self):
        ocr_text = "Take 1 tablet by mouth twice daily"
        vlm_text = "Take 1 tablet by mouth once daily"
        result = reconcile_fields(
            {"instructions": field(ocr_text, 0.9)},
            {"instructions": field(vlm_text, 0.5, "vlm")},
        )
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.ocr_value == ocr_text
        assert conflict.vlm_value == vlm_text
        assert conflict.chosen_source == "ocr"
        assert conflict.reason  # never silent
        payload = conflict.to_dict()
        assert payload["ocr_value"] == ocr_text and payload["vlm_value"] == vlm_text
        assert payload["reason"]

    def test_real_name_conflict_reports_reason(self):
        result = reconcile_fields(
            {"name": field("Metformin", 0.4)},
            {"name": field("Metronidazole", 0.95, "vlm")},
        )
        assert len(result.conflicts) == 1
        assert result.fields["name"]["source"] == "vlm"
        assert "vlm" in result.conflicts[0].reason
        assert "0.40" in result.conflicts[0].reason


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
