"""Unit tests for the dimension_completeness rule module.

Tests cover concrete fixtures for each of the four rules:
- SizeDimensionRule
- PositionDimensionRule
- OverDimensionRule
- AngularDimensionRule
"""

import pytest

from engineering_drawing_analyzer.models import (
    Datum,
    Dimension,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    Issue,
    LocationReference,
    Point2D,
    Severity,
    Tolerance,
)
from engineering_drawing_analyzer.rule_engine.dimension_completeness import (
    AngularDimensionRule,
    OverDimensionRule,
    PositionDimensionRule,
    SizeDimensionRule,
)
from engineering_drawing_analyzer.rule_engine.engine import RuleEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(view: str = "FRONT") -> LocationReference:
    return LocationReference(view_name=view, coordinates=Point2D(0.0, 0.0), label=None)


def _dim(
    id: str,
    value: float = 10.0,
    unit: str = "mm",
    feature_ids: list[str] | None = None,
) -> Dimension:
    return Dimension(
        id=id,
        value=value,
        unit=unit,
        tolerance=Tolerance(upper=0.1, lower=-0.1),
        location=_loc(),
        associated_feature_ids=feature_ids or [],
    )


def _angular_dim(id: str, value: float = 45.0, feature_ids: list[str] | None = None) -> Dimension:
    return Dimension(
        id=id,
        value=value,
        unit="ANGULAR",
        tolerance=Tolerance(upper=0.5, lower=-0.5),
        location=_loc(),
        associated_feature_ids=feature_ids or [],
    )


def _feature(
    id: str,
    feature_type: str = "HOLE",
    dims: list[Dimension] | None = None,
    is_angular: bool = False,
) -> Feature:
    return Feature(
        id=id,
        feature_type=feature_type,
        dimensions=dims or [],
        location=_loc(),
        is_angular=is_angular,
    )


def _datum(label: str, feature_id: str) -> Datum:
    return Datum(label=label, feature_id=feature_id, location=_loc())


# ---------------------------------------------------------------------------
# SizeDimensionRule
# ---------------------------------------------------------------------------


class TestSizeDimensionRule:
    rule = SizeDimensionRule()

    def test_feature_with_size_dimension_passes(self):
        feature = _feature("F1", dims=[_dim("D1", unit="mm")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_without_any_dimension_raises_critical(self):
        feature = _feature("F1", dims=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "MISSING_SIZE_DIMENSION"
        assert "F1" in issue.description
        assert issue.corrective_action  # non-empty
        assert issue.standard_reference  # non-empty

    def test_feature_with_only_angular_dimension_raises_critical(self):
        """An angular dimension does not count as a size dimension."""
        feature = _feature("F2", dims=[_angular_dim("D_ANG")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_SIZE_DIMENSION"

    def test_multiple_features_each_missing_size_dimension(self):
        features = [_feature(f"F{i}", dims=[]) for i in range(3)]
        model = GeometricModel(features=features)
        issues = self.rule.check(model)
        assert len(issues) == 3
        for issue in issues:
            assert issue.severity == Severity.CRITICAL

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_corrective_action_and_standard_reference_present(self):
        feature = _feature("F1", dims=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues[0].corrective_action
        assert "ASME Y14.5" in issues[0].standard_reference

    def test_feature_with_diameter_dimension_passes(self):
        dim = _dim("D1", unit="DIAMETER")
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_with_radial_dimension_passes(self):
        dim = _dim("D1", unit="RADIAL")
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []


# ---------------------------------------------------------------------------
# PositionDimensionRule
# ---------------------------------------------------------------------------


class TestPositionDimensionRule:
    rule = PositionDimensionRule()

    def test_feature_with_linear_dimension_passes(self):
        """A LINEAR dimension counts as a position dimension."""
        feature = _feature("F1", dims=[_dim("D1", unit="mm")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_without_position_dimension_raises_critical(self):
        """A feature with only an angular dimension has no position info."""
        feature = _feature("F1", dims=[_angular_dim("D_ANG")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "MISSING_POSITION_DIMENSION"
        assert issue.corrective_action
        assert issue.standard_reference

    def test_datum_feature_is_exempt(self):
        """A feature that IS a datum does not need a separate position dimension."""
        feature = _feature("F1", dims=[])
        datum = _datum("A", feature_id="F1")
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_with_gdt_position_fcf_passes(self):
        """A GD&T position FCF referencing a defined datum satisfies the rule."""
        datum = _datum("A", feature_id="F_REF")
        fcf = FeatureControlFrame(
            id="FCF1",
            gdt_symbol="⊕",
            tolerance_value=0.05,
            datum_references=["A"],
            material_condition=None,
            location=_loc(),
        )
        feature = Feature(
            id="F1",
            feature_type="HOLE",
            dimensions=[],
            feature_control_frames=[fcf],
            location=_loc(),
        )
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_with_no_dimensions_and_no_datum_raises_critical(self):
        feature = _feature("F1", dims=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.CRITICAL

    def test_top_level_dimension_referencing_feature_counts(self):
        """A top-level dimension that references the feature satisfies the rule."""
        feature = _feature("F1", dims=[])
        top_dim = _dim("D_TOP", unit="mm", feature_ids=["F1"])
        model = GeometricModel(features=[feature], dimensions=[top_dim])
        issues = self.rule.check(model)
        assert issues == []


# ---------------------------------------------------------------------------
# OverDimensionRule
# ---------------------------------------------------------------------------


class TestOverDimensionRule:
    rule = OverDimensionRule()

    def test_single_dimension_no_warning(self):
        feature = _feature("F1", dims=[_dim("D1")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_two_dimensions_same_type_produces_warning(self):
        """Two LINEAR dimensions on the same feature → WARNING."""
        feature = _feature("F1", dims=[_dim("D1", value=10.0), _dim("D2", value=12.0)])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.WARNING
        assert issue.issue_type == "OVER_DIMENSION"
        assert "F1" in issue.description

    def test_two_identical_dimensions_still_produces_warning(self):
        """Even identical redundant dimensions are flagged."""
        feature = _feature("F1", dims=[_dim("D1", value=10.0), _dim("D2", value=10.0)])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING

    def test_size_and_angular_dimension_no_warning(self):
        """Different dimension types on the same feature are not conflicting."""
        feature = _feature(
            "F1",
            dims=[_dim("D1", unit="mm"), _angular_dim("D_ANG")],
            is_angular=True,
        )
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        # No over-dimension warning because they are different types.
        over_dim_issues = [i for i in issues if i.issue_type == "OVER_DIMENSION"]
        assert over_dim_issues == []

    def test_top_level_dimension_included_in_check(self):
        """Top-level dimensions referencing a feature are included in the check."""
        feature = _feature("F1", dims=[_dim("D1", value=10.0)])
        top_dim = _dim("D_TOP", value=15.0, feature_ids=["F1"])
        model = GeometricModel(features=[feature], dimensions=[top_dim])
        issues = self.rule.check(model)
        over_dim_issues = [i for i in issues if i.issue_type == "OVER_DIMENSION"]
        assert len(over_dim_issues) == 1

    def test_corrective_action_present_in_warning(self):
        feature = _feature("F1", dims=[_dim("D1"), _dim("D2")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues[0].corrective_action

    def test_standard_reference_present_in_warning(self):
        feature = _feature("F1", dims=[_dim("D1"), _dim("D2")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert "ASME Y14.5" in issues[0].standard_reference


# ---------------------------------------------------------------------------
# AngularDimensionRule
# ---------------------------------------------------------------------------


class TestAngularDimensionRule:
    rule = AngularDimensionRule()

    def test_non_angular_feature_not_checked(self):
        feature = _feature("F1", is_angular=False, dims=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_angular_feature_with_angular_dimension_passes(self):
        feature = _feature("F1", is_angular=True, dims=[_angular_dim("D_ANG")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_angular_feature_without_angular_dimension_raises_critical(self):
        feature = _feature("F1", is_angular=True, dims=[_dim("D1", unit="mm")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "MISSING_ANGULAR_DIMENSION"
        assert "F1" in issue.description
        assert issue.corrective_action
        assert issue.standard_reference

    def test_angular_feature_with_no_dimensions_raises_critical(self):
        feature = _feature("F1", is_angular=True, dims=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.CRITICAL

    def test_top_level_angular_dimension_satisfies_rule(self):
        """A top-level angular dimension referencing the feature satisfies the rule."""
        feature = _feature("F1", is_angular=True, dims=[])
        top_ang_dim = _angular_dim("D_ANG_TOP", feature_ids=["F1"])
        model = GeometricModel(features=[feature], dimensions=[top_ang_dim])
        issues = self.rule.check(model)
        assert issues == []

    def test_corrective_action_and_standard_reference_present(self):
        feature = _feature("F1", is_angular=True, dims=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues[0].corrective_action
        assert "ASME Y14.5" in issues[0].standard_reference

    def test_multiple_angular_features_each_missing_angular_dim(self):
        features = [_feature(f"F{i}", is_angular=True, dims=[]) for i in range(4)]
        model = GeometricModel(features=features)
        issues = self.rule.check(model)
        assert len(issues) == 4
        for issue in issues:
            assert issue.severity == Severity.CRITICAL


# ---------------------------------------------------------------------------
# RuleEngine integration
# ---------------------------------------------------------------------------


class TestRuleEngine:
    def test_run_returns_combined_issues(self):
        """RuleEngine.run() aggregates issues from all registered rules."""
        feature_no_size = _feature("F1", dims=[])
        feature_angular_no_ang = _feature("F2", is_angular=True, dims=[_dim("D1")])
        model = GeometricModel(features=[feature_no_size, feature_angular_no_ang])

        engine = RuleEngine(
            rules=[SizeDimensionRule(), AngularDimensionRule()]
        )
        issues = engine.run(model)

        issue_types = {i.issue_type for i in issues}
        assert "MISSING_SIZE_DIMENSION" in issue_types
        assert "MISSING_ANGULAR_DIMENSION" in issue_types

    def test_run_catches_rule_exception_and_appends_info_issue(self):
        """A rule that raises an exception should not abort the engine."""

        class BrokenRule:
            rule_id = "BROKEN_RULE"

            def check(self, model: GeometricModel) -> list[Issue]:
                raise RuntimeError("Simulated rule failure")

        class GoodRule:
            rule_id = "GOOD_RULE"

            def check(self, model: GeometricModel) -> list[Issue]:
                return [
                    Issue(
                        issue_id="test-id",
                        rule_id="GOOD_RULE",
                        issue_type="TEST_ISSUE",
                        severity=Severity.INFO,
                        description="Good rule ran.",
                        location=_loc(),
                    )
                ]

        engine = RuleEngine(rules=[BrokenRule(), GoodRule()])
        issues = engine.run(GeometricModel())

        # The broken rule should produce an INFO issue.
        info_issues = [i for i in issues if i.rule_id == "BROKEN_RULE"]
        assert len(info_issues) == 1
        assert info_issues[0].severity == Severity.INFO
        assert info_issues[0].issue_type == "RULE_ENGINE_ERROR"

        # The good rule should still have run.
        good_issues = [i for i in issues if i.rule_id == "GOOD_RULE"]
        assert len(good_issues) == 1

    def test_run_empty_rules_returns_empty_list(self):
        engine = RuleEngine(rules=[])
        issues = engine.run(GeometricModel())
        assert issues == []

    def test_run_empty_model_no_issues(self):
        engine = RuleEngine(
            rules=[
                SizeDimensionRule(),
                PositionDimensionRule(),
                OverDimensionRule(),
                AngularDimensionRule(),
            ]
        )
        issues = engine.run(GeometricModel())
        assert issues == []
