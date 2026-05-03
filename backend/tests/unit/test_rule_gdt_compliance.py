"""Unit tests for the gdt_compliance rule module.

Tests cover concrete fixtures for each of the three rules:
- GDTSymbolSetRule
- CompositeFCFRule
- DatumFeatureSymbolPlacementRule
"""

import pytest

from engineering_drawing_analyzer.models import (
    Datum,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    LocationReference,
    Point2D,
    Severity,
)
from engineering_drawing_analyzer.rule_engine.gdt_compliance import (
    CompositeFCFRule,
    DatumFeatureSymbolPlacementRule,
    GDTSymbolSetRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(view: str = "FRONT") -> LocationReference:
    return LocationReference(view_name=view, coordinates=Point2D(0.0, 0.0), label=None)


def _fcf(
    id: str,
    gdt_symbol: str = "⊕",
    tolerance_value: float | None = 0.05,
    datum_references: list[str] | None = None,
) -> FeatureControlFrame:
    return FeatureControlFrame(
        id=id,
        gdt_symbol=gdt_symbol,
        tolerance_value=tolerance_value,
        datum_references=datum_references if datum_references is not None else [],
        material_condition=None,
        location=_loc(),
    )


def _feature(
    id: str,
    feature_type: str = "HOLE",
    fcfs: list[FeatureControlFrame] | None = None,
) -> Feature:
    return Feature(
        id=id,
        feature_type=feature_type,
        dimensions=[],
        feature_control_frames=fcfs or [],
        location=_loc(),
    )


def _datum(label: str, feature_id: str = "F1") -> Datum:
    return Datum(label=label, feature_id=feature_id, location=_loc())


# ---------------------------------------------------------------------------
# GDTSymbolSetRule
# ---------------------------------------------------------------------------


class TestGDTSymbolSetRule:
    rule = GDTSymbolSetRule()

    # --- Standard Unicode symbols ---

    def test_straightness_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⏤")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_flatness_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⏥")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_circularity_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="○")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_cylindricity_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⌭")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_profile_of_a_line_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⌒")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_profile_of_a_surface_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⌓")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_angularity_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="∠")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_perpendicularity_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⊥")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_parallelism_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="∥")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_position_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⊕")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_concentricity_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="◎")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_symmetry_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="≡")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_circular_runout_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="↗")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_total_runout_unicode_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="⇗")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    # --- Standard ASCII/text equivalents ---

    def test_position_text_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="POSITION")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_flatness_text_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="FLATNESS")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_perpendicularity_text_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="PERPENDICULARITY")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_true_position_text_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="TRUE_POSITION")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_cylindricity_text_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="CYLINDRICITY")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_total_runout_text_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="TOTAL_RUNOUT")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    # --- Non-standard symbols ---

    def test_unknown_symbol_produces_warning(self):
        fcf = _fcf("FCF1", gdt_symbol="UNKNOWN_SYMBOL")
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.WARNING
        assert issue.issue_type == "NON_STANDARD_GDT_SYMBOL"
        assert "UNKNOWN_SYMBOL" in issue.description
        assert "FCF1" in issue.description

    def test_empty_symbol_produces_warning(self):
        fcf = _fcf("FCF1", gdt_symbol="")
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "NON_STANDARD_GDT_SYMBOL"

    def test_typo_symbol_produces_warning(self):
        """A symbol with a typo (e.g. 'POSTION') is non-standard."""
        fcf = _fcf("FCF1", gdt_symbol="POSTION")
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_multiple_non_standard_symbols_each_produce_warning(self):
        fcfs = [
            _fcf("FCF1", gdt_symbol="BAD_SYMBOL_1"),
            _fcf("FCF2", gdt_symbol="BAD_SYMBOL_2"),
        ]
        model = GeometricModel(feature_control_frames=fcfs)
        issues = self.rule.check(model)
        assert len(issues) == 2
        for issue in issues:
            assert issue.severity == Severity.WARNING

    def test_mixed_standard_and_non_standard_only_flags_non_standard(self):
        fcfs = [
            _fcf("FCF1", gdt_symbol="⊕"),       # standard
            _fcf("FCF2", gdt_symbol="WEIRD"),    # non-standard
            _fcf("FCF3", gdt_symbol="FLATNESS"), # standard
        ]
        model = GeometricModel(feature_control_frames=fcfs)
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert "FCF2" in issues[0].description

    def test_feature_level_fcf_is_checked(self):
        """FCFs attached to features are also validated."""
        fcf = _fcf("FCF1", gdt_symbol="NOT_STANDARD")
        feature = _feature("F1", fcfs=[fcf])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "NON_STANDARD_GDT_SYMBOL"

    def test_feature_level_fcf_not_double_counted(self):
        """An FCF appearing both top-level and on a feature is counted once."""
        fcf = _fcf("FCF1", gdt_symbol="NOT_STANDARD")
        feature = _feature("F1", fcfs=[fcf])
        model = GeometricModel(features=[feature], feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        assert self.rule.check(model) == []

    def test_standard_reference_present(self):
        fcf = _fcf("FCF1", gdt_symbol="BAD")
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert issues[0].standard_reference is not None
        assert "Y14.5" in issues[0].standard_reference

    def test_case_insensitive_text_symbol_passes(self):
        """Text symbols should be matched case-insensitively."""
        fcf = _fcf("FCF1", gdt_symbol="flatness")
        model = GeometricModel(feature_control_frames=[fcf])
        # lowercase "flatness" should match "FLATNESS"
        assert self.rule.check(model) == []

    def test_profile_of_a_line_with_spaces_passes(self):
        fcf = _fcf("FCF1", gdt_symbol="PROFILE OF A LINE")
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []


# ---------------------------------------------------------------------------
# CompositeFCFRule
# ---------------------------------------------------------------------------


class TestCompositeFCFRule:
    rule = CompositeFCFRule()

    def test_position_fcf_with_datums_and_positive_tolerance_passes(self):
        """A well-formed PLTZF (position + datums + positive tolerance) passes."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=0.5, datum_references=["A", "B"])
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_position_fcf_without_datums_is_not_checked(self):
        """A position FCF without datum references is not a composite FCF candidate."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=0.05, datum_references=[])
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_non_position_fcf_is_not_checked(self):
        """Only position FCFs are checked for composite FCF rules."""
        fcf = _fcf("FCF1", gdt_symbol="⊥", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        # CompositeFCFRule should not flag this (it's not a position symbol)
        issues = self.rule.check(model)
        assert issues == []

    def test_position_fcf_with_datums_and_none_tolerance_raises_critical(self):
        """PLTZF with missing tolerance value → CRITICAL."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "COMPOSITE_FCF_INVALID_PLTZF_TOLERANCE"
        assert "FCF1" in issue.description
        assert issue.corrective_action is not None
        assert issue.standard_reference is not None

    def test_position_fcf_with_datums_and_zero_tolerance_raises_critical(self):
        """PLTZF with zero tolerance value → CRITICAL."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=0.0, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "COMPOSITE_FCF_INVALID_PLTZF_TOLERANCE"

    def test_position_fcf_with_datums_and_negative_tolerance_raises_critical(self):
        """PLTZF with negative tolerance value → CRITICAL."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=-0.1, datum_references=["A", "B"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.CRITICAL

    def test_text_position_symbol_with_datums_and_none_tolerance_raises_critical(self):
        """Text-based 'POSITION' symbol is also checked."""
        fcf = _fcf("FCF1", gdt_symbol="POSITION", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "COMPOSITE_FCF_INVALID_PLTZF_TOLERANCE"

    def test_true_position_text_symbol_with_datums_and_none_tolerance_raises_critical(self):
        fcf = _fcf("FCF1", gdt_symbol="TRUE_POSITION", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_corrective_action_references_asme_y14_5(self):
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert "ASME Y14.5" in issues[0].standard_reference
        assert "11.10" in issues[0].standard_reference

    def test_feature_level_composite_fcf_is_checked(self):
        """Composite FCFs attached to features are also checked."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"])
        feature = _feature("F1", fcfs=[fcf])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        assert self.rule.check(model) == []

    def test_flatness_with_datums_and_none_tolerance_not_flagged(self):
        """Flatness is not a position symbol; CompositeFCFRule ignores it."""
        fcf = _fcf("FCF1", gdt_symbol="⏥", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        assert self.rule.check(model) == []

    def test_multiple_malformed_composite_fcfs_each_produce_critical(self):
        fcfs = [
            _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"]),
            _fcf("FCF2", gdt_symbol="⊕", tolerance_value=0.0, datum_references=["B"]),
        ]
        model = GeometricModel(feature_control_frames=fcfs)
        issues = self.rule.check(model)
        assert len(issues) == 2
        for issue in issues:
            assert issue.severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# DatumFeatureSymbolPlacementRule
# ---------------------------------------------------------------------------


class TestDatumFeatureSymbolPlacementRule:
    rule = DatumFeatureSymbolPlacementRule()

    def test_datum_on_physical_feature_passes(self):
        """A datum applied to a HOLE (physical feature) is correct."""
        feature = _feature("F1", feature_type="HOLE")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        assert self.rule.check(model) == []

    def test_datum_on_surface_feature_passes(self):
        feature = _feature("F1", feature_type="SURFACE")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        assert self.rule.check(model) == []

    def test_datum_on_slot_feature_passes(self):
        feature = _feature("F1", feature_type="SLOT")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        assert self.rule.check(model) == []

    def test_datum_with_empty_feature_id_produces_warning(self):
        """A datum with no feature_id is incorrectly placed."""
        datum = _datum("A", feature_id="")
        model = GeometricModel(datums=[datum])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.WARNING
        assert issue.issue_type == "DATUM_SYMBOL_NO_FEATURE"
        assert "A" in issue.description

    def test_datum_on_centerline_feature_produces_warning(self):
        """A datum applied to a CENTERLINE feature is incorrect."""
        feature = _feature("F1", feature_type="CENTERLINE")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.WARNING
        assert issue.issue_type == "DATUM_SYMBOL_ON_NON_PHYSICAL_FEATURE"
        assert "A" in issue.description
        assert "F1" in issue.description

    def test_datum_on_axis_feature_produces_warning(self):
        """A datum applied to an AXIS feature is incorrect."""
        feature = _feature("F1", feature_type="AXIS")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "DATUM_SYMBOL_ON_NON_PHYSICAL_FEATURE"

    def test_datum_on_center_axis_feature_produces_warning(self):
        feature = _feature("F1", feature_type="CENTER_AXIS")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "DATUM_SYMBOL_ON_NON_PHYSICAL_FEATURE"

    def test_datum_on_centreline_feature_produces_warning(self):
        """British spelling variant 'CENTRELINE' is also flagged."""
        feature = _feature("F1", feature_type="CENTRELINE")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_datum_on_centre_axis_feature_produces_warning(self):
        feature = _feature("F1", feature_type="CENTRE_AXIS")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_datum_feature_type_case_insensitive(self):
        """Feature type matching is case-insensitive."""
        feature = _feature("F1", feature_type="centerline")
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "DATUM_SYMBOL_ON_NON_PHYSICAL_FEATURE"

    def test_datum_referencing_unknown_feature_id_does_not_raise(self):
        """A datum whose feature_id doesn't match any feature in the model is silently skipped."""
        datum = _datum("A", feature_id="NONEXISTENT_FEATURE")
        model = GeometricModel(datums=[datum])
        # Should not raise; the feature simply isn't in the model
        issues = self.rule.check(model)
        assert issues == []

    def test_multiple_datums_mixed_correct_and_incorrect(self):
        """Only incorrectly placed datums produce warnings."""
        feature_hole = _feature("F1", feature_type="HOLE")
        feature_axis = _feature("F2", feature_type="AXIS")
        datum_ok = _datum("A", feature_id="F1")
        datum_bad = _datum("B", feature_id="F2")
        model = GeometricModel(
            features=[feature_hole, feature_axis],
            datums=[datum_ok, datum_bad],
        )
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert "B" in issues[0].description

    def test_standard_reference_present(self):
        datum = _datum("A", feature_id="")
        model = GeometricModel(datums=[datum])
        issues = self.rule.check(model)
        assert issues[0].standard_reference is not None
        assert "Y14.5" in issues[0].standard_reference

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        assert self.rule.check(model) == []

    def test_multiple_datums_all_incorrect_each_produce_warning(self):
        feature_cl = _feature("F1", feature_type="CENTERLINE")
        feature_ax = _feature("F2", feature_type="AXIS")
        datum_a = _datum("A", feature_id="F1")
        datum_b = _datum("B", feature_id="F2")
        datum_c = _datum("C", feature_id="")
        model = GeometricModel(
            features=[feature_cl, feature_ax],
            datums=[datum_a, datum_b, datum_c],
        )
        issues = self.rule.check(model)
        assert len(issues) == 3
        for issue in issues:
            assert issue.severity == Severity.WARNING
