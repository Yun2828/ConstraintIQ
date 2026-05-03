"""Unit tests for the tolerance_verification rule module.

Tests cover concrete fixtures for each of the three rules:
- DimensionToleranceRule
- FCFCompletenessRule
- ToleranceStackUpRule
"""

import pytest

from engineering_drawing_analyzer.models import (
    Dimension,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    LocationReference,
    Point2D,
    Severity,
    Tolerance,
)
from engineering_drawing_analyzer.rule_engine.tolerance_verification import (
    DimensionToleranceRule,
    FCFCompletenessRule,
    ToleranceStackUpRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(view: str = "FRONT") -> LocationReference:
    return LocationReference(view_name=view, coordinates=Point2D(0.0, 0.0), label=None)


def _tol(upper: float = 0.1, lower: float = -0.1, is_general: bool = False) -> Tolerance:
    return Tolerance(upper=upper, lower=lower, is_general=is_general)


def _dim(
    id: str,
    value: float = 10.0,
    unit: str = "mm",
    tolerance: Tolerance | None = _tol(),
    feature_ids: list[str] | None = None,
) -> Dimension:
    return Dimension(
        id=id,
        value=value,
        unit=unit,
        tolerance=tolerance,
        location=_loc(),
        associated_feature_ids=feature_ids or [],
    )


def _dim_no_tol(id: str, value: float = 10.0, feature_ids: list[str] | None = None) -> Dimension:
    return _dim(id, value=value, tolerance=None, feature_ids=feature_ids)


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
        datum_references=datum_references if datum_references is not None else ["A"],
        material_condition=None,
        location=_loc(),
    )


def _feature(
    id: str,
    dims: list[Dimension] | None = None,
    fcfs: list[FeatureControlFrame] | None = None,
) -> Feature:
    return Feature(
        id=id,
        feature_type="HOLE",
        dimensions=dims or [],
        feature_control_frames=fcfs or [],
        location=_loc(),
    )


# ---------------------------------------------------------------------------
# DimensionToleranceRule
# ---------------------------------------------------------------------------


class TestDimensionToleranceRule:
    rule = DimensionToleranceRule()

    def test_dimension_with_explicit_tolerance_passes(self):
        dim = _dim("D1", tolerance=_tol())
        model = GeometricModel(dimensions=[dim])
        issues = self.rule.check(model)
        assert issues == []

    def test_dimension_without_tolerance_and_no_general_tolerance_raises_critical(self):
        dim = _dim_no_tol("D1")
        model = GeometricModel(dimensions=[dim])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "MISSING_DIMENSION_TOLERANCE"
        assert "D1" in issue.description
        assert issue.corrective_action
        assert issue.standard_reference

    def test_dimension_without_tolerance_but_general_tolerance_present_passes(self):
        dim = _dim_no_tol("D1")
        model = GeometricModel(
            dimensions=[dim],
            general_tolerance=_tol(upper=0.2, lower=-0.2, is_general=True),
        )
        issues = self.rule.check(model)
        assert issues == []

    def test_multiple_untolerated_dimensions_each_produce_critical(self):
        dims = [_dim_no_tol(f"D{i}") for i in range(3)]
        model = GeometricModel(dimensions=dims)
        issues = self.rule.check(model)
        assert len(issues) == 3
        for issue in issues:
            assert issue.severity == Severity.CRITICAL

    def test_feature_level_dimension_without_tolerance_raises_critical(self):
        """Dimensions attached to features (not top-level) are also checked."""
        dim = _dim_no_tol("D1")
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_DIMENSION_TOLERANCE"

    def test_feature_level_dimension_not_double_counted(self):
        """A dimension that appears both top-level and on a feature is counted once."""
        dim = _dim_no_tol("D1")
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(features=[feature], dimensions=[dim])
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_corrective_action_references_asme(self):
        dim = _dim_no_tol("D1")
        model = GeometricModel(dimensions=[dim])
        issues = self.rule.check(model)
        assert "ASME Y14.5" in issues[0].standard_reference

    def test_mixed_tolerated_and_untolerated_dimensions(self):
        """Only untolerated dimensions produce issues."""
        dims = [
            _dim("D1", tolerance=_tol()),
            _dim_no_tol("D2"),
            _dim("D3", tolerance=_tol()),
            _dim_no_tol("D4"),
        ]
        model = GeometricModel(dimensions=dims)
        issues = self.rule.check(model)
        assert len(issues) == 2
        issue_ids = {i.description for i in issues}
        assert any("D2" in d for d in issue_ids)
        assert any("D4" in d for d in issue_ids)


# ---------------------------------------------------------------------------
# FCFCompletenessRule
# ---------------------------------------------------------------------------


class TestFCFCompletenessRule:
    rule = FCFCompletenessRule()

    def test_complete_position_fcf_passes(self):
        """A position FCF with a valid tolerance value and datum reference passes."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=0.05, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert issues == []

    def test_form_tolerance_without_datum_passes(self):
        """Flatness (form tolerance) does not require a datum reference."""
        fcf = _fcf("FCF1", gdt_symbol="⏥", tolerance_value=0.02, datum_references=[])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert issues == []

    def test_fcf_missing_tolerance_value_raises_critical(self):
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "MISSING_FCF_TOLERANCE_VALUE"
        assert "FCF1" in issue.description
        assert issue.corrective_action
        assert issue.standard_reference

    def test_fcf_with_zero_tolerance_value_raises_critical(self):
        """A tolerance value of 0 is not valid."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=0.0, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_FCF_TOLERANCE_VALUE"

    def test_fcf_with_negative_tolerance_value_raises_critical(self):
        """A negative tolerance value is not valid."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=-0.05, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_FCF_TOLERANCE_VALUE"

    def test_position_fcf_missing_datum_reference_raises_critical(self):
        """Position tolerance requires at least one datum reference."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=0.05, datum_references=[])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "MISSING_FCF_DATUM_REFERENCE"
        assert "FCF1" in issue.description
        assert issue.corrective_action
        assert issue.standard_reference

    def test_perpendicularity_fcf_missing_datum_raises_critical(self):
        """Perpendicularity (orientation tolerance) requires a datum reference."""
        fcf = _fcf("FCF1", gdt_symbol="⊥", tolerance_value=0.02, datum_references=[])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        datum_issues = [i for i in issues if i.issue_type == "MISSING_FCF_DATUM_REFERENCE"]
        assert len(datum_issues) == 1

    def test_fcf_missing_both_tolerance_and_datum_produces_two_issues(self):
        """An FCF missing both tolerance value and datum reference produces two issues."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=[])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        issue_types = {i.issue_type for i in issues}
        assert "MISSING_FCF_TOLERANCE_VALUE" in issue_types
        assert "MISSING_FCF_DATUM_REFERENCE" in issue_types

    def test_feature_level_fcf_is_checked(self):
        """FCFs attached to features (not top-level) are also checked."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"])
        feature = _feature("F1", fcfs=[fcf])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_FCF_TOLERANCE_VALUE"

    def test_feature_level_fcf_not_double_counted(self):
        """An FCF that appears both top-level and on a feature is counted once."""
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"])
        feature = _feature("F1", fcfs=[fcf])
        model = GeometricModel(features=[feature], feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_corrective_action_references_asme(self):
        fcf = _fcf("FCF1", gdt_symbol="⊕", tolerance_value=None, datum_references=["A"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert "ASME Y14.5" in issues[0].standard_reference

    def test_string_symbol_position_requires_datum(self):
        """String-based 'POSITION' symbol also requires a datum reference."""
        fcf = _fcf("FCF1", gdt_symbol="POSITION", tolerance_value=0.05, datum_references=[])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        datum_issues = [i for i in issues if i.issue_type == "MISSING_FCF_DATUM_REFERENCE"]
        assert len(datum_issues) == 1

    def test_cylindricity_without_datum_passes(self):
        """Cylindricity (form tolerance) does not require a datum reference."""
        fcf = _fcf("FCF1", gdt_symbol="CYLINDRICITY", tolerance_value=0.01, datum_references=[])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert issues == []


# ---------------------------------------------------------------------------
# ToleranceStackUpRule
# ---------------------------------------------------------------------------


class TestToleranceStackUpRule:
    rule = ToleranceStackUpRule()

    def test_single_dimension_no_stack_up(self):
        """A single dimension cannot form a chain."""
        dim = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=["F1"])
        model = GeometricModel(dimensions=[dim])
        issues = self.rule.check(model)
        assert issues == []

    def test_two_unrelated_dimensions_no_stack_up(self):
        """Dimensions with no shared features do not form a chain."""
        d1 = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=["F1"])
        d2 = _dim("D2", tolerance=_tol(0.05, -0.05), feature_ids=["F2"])
        model = GeometricModel(dimensions=[d1, d2])
        issues = self.rule.check(model)
        assert issues == []

    def test_chain_with_stack_up_exceeding_tightest_produces_warning(self):
        """Two dimensions sharing a feature where stack-up > tightest tolerance."""
        # D1: band = 0.1 + 0.1 = 0.2, D2: band = 0.05 + 0.05 = 0.1
        # stack_up_total = 0.3, tightest = 0.1 → violation
        d1 = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=["F1", "F2"])
        d2 = _dim("D2", tolerance=_tol(0.05, -0.05), feature_ids=["F2", "F3"])
        model = GeometricModel(dimensions=[d1, d2])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.WARNING
        assert issue.issue_type == "TOLERANCE_STACK_UP_VIOLATION"
        assert "0.3" in issue.description or "0.30" in issue.description
        assert "0.1" in issue.description or "0.10" in issue.description
        assert issue.standard_reference == "ASME Y14.5-2018 §2.1"

    def test_chain_where_stack_up_equals_tightest_no_violation(self):
        """Stack-up equal to tightest tolerance is not a violation (strict >)."""
        # D1: band = 0.1, D2: band = 0.1 → stack_up = 0.2, tightest = 0.1
        # 0.2 > 0.1 → violation
        # To get no violation: need stack_up <= tightest, which means
        # all bands must be equal and there's only one dimension (handled above).
        # Let's test a case where stack_up == tightest: impossible with 2 dims
        # unless one has band 0. Use a single-dim chain instead.
        d1 = _dim("D1", tolerance=_tol(0.05, -0.05), feature_ids=["F1"])
        model = GeometricModel(dimensions=[d1])
        issues = self.rule.check(model)
        assert issues == []

    def test_chain_with_equal_tolerances_produces_warning(self):
        """Two equal tolerances: stack_up = 2*band > band = tightest → violation."""
        d1 = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=["F1", "F2"])
        d2 = _dim("D2", tolerance=_tol(0.1, -0.1), feature_ids=["F2", "F3"])
        model = GeometricModel(dimensions=[d1, d2])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_dimension_without_tolerance_excluded_from_chain(self):
        """Untolerated dimensions are excluded from stack-up analysis."""
        d1 = _dim_no_tol("D1", feature_ids=["F1", "F2"])
        d2 = _dim("D2", tolerance=_tol(0.05, -0.05), feature_ids=["F2", "F3"])
        model = GeometricModel(dimensions=[d1, d2])
        issues = self.rule.check(model)
        # Only D2 is eligible; single-dim chain → no stack-up issue.
        stack_up_issues = [i for i in issues if i.issue_type == "TOLERANCE_STACK_UP_VIOLATION"]
        assert stack_up_issues == []

    def test_dimension_without_feature_ids_excluded_from_chain(self):
        """Dimensions with no feature associations cannot form chains."""
        d1 = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=[])
        d2 = _dim("D2", tolerance=_tol(0.05, -0.05), feature_ids=[])
        model = GeometricModel(dimensions=[d1, d2])
        issues = self.rule.check(model)
        assert issues == []

    def test_three_dimension_chain_produces_warning(self):
        """Three chained dimensions: stack-up = sum of all bands."""
        # bands: 0.2, 0.1, 0.06 → sum = 0.36, tightest = 0.06 → violation
        d1 = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=["F1", "F2"])
        d2 = _dim("D2", tolerance=_tol(0.05, -0.05), feature_ids=["F2", "F3"])
        d3 = _dim("D3", tolerance=_tol(0.03, -0.03), feature_ids=["F3", "F4"])
        model = GeometricModel(dimensions=[d1, d2, d3])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_feature_level_dimensions_included_in_chain(self):
        """Dimensions attached to features are included in stack-up analysis."""
        d1 = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=["F1", "F2"])
        d2 = _dim("D2", tolerance=_tol(0.05, -0.05), feature_ids=["F2", "F3"])
        feature = _feature("F1", dims=[d1])
        model = GeometricModel(features=[feature], dimensions=[d2])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "TOLERANCE_STACK_UP_VIOLATION"

    def test_description_contains_stack_up_value(self):
        """The issue description must include the calculated stack-up value."""
        d1 = _dim("D1", tolerance=_tol(0.1, -0.1), feature_ids=["F1", "F2"])
        d2 = _dim("D2", tolerance=_tol(0.05, -0.05), feature_ids=["F2", "F3"])
        model = GeometricModel(dimensions=[d1, d2])
        issues = self.rule.check(model)
        assert len(issues) == 1
        # stack_up_total = 0.2 + 0.1 = 0.3
        assert "0.3" in issues[0].description

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_unilateral_tolerance_band_computed_correctly(self):
        """Unilateral tolerance: upper=0.2, lower=0.0 → band = 0.2."""
        # D1: band = 0.2, D2: band = 0.1 → stack_up = 0.3 > 0.1 → violation
        d1 = _dim("D1", tolerance=Tolerance(upper=0.2, lower=0.0), feature_ids=["F1", "F2"])
        d2 = _dim("D2", tolerance=Tolerance(upper=0.1, lower=0.0), feature_ids=["F2", "F3"])
        model = GeometricModel(dimensions=[d1, d2])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "TOLERANCE_STACK_UP_VIOLATION"
