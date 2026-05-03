"""Unit tests for the geometric_constraints rule module.

Tests cover concrete fixtures for each of the three rules:
- DatumReferenceFrameRule
- FeatureOrientationRule
- GDTDatumReferenceRule
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
from engineering_drawing_analyzer.rule_engine.geometric_constraints import (
    DatumReferenceFrameRule,
    FeatureOrientationRule,
    GDTDatumReferenceRule,
)


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


def _feature(
    id: str,
    feature_type: str = "HOLE",
    dims: list[Dimension] | None = None,
    fcfs: list[FeatureControlFrame] | None = None,
) -> Feature:
    return Feature(
        id=id,
        feature_type=feature_type,
        dimensions=dims or [],
        feature_control_frames=fcfs or [],
        location=_loc(),
    )


def _datum(label: str, feature_id: str = "F_REF") -> Datum:
    return Datum(label=label, feature_id=feature_id, location=_loc())


def _fcf(
    id: str,
    gdt_symbol: str = "⊕",
    datum_refs: list[str] | None = None,
) -> FeatureControlFrame:
    return FeatureControlFrame(
        id=id,
        gdt_symbol=gdt_symbol,
        tolerance_value=0.05,
        datum_references=datum_refs or [],
        material_condition=None,
        location=_loc(),
    )


# ---------------------------------------------------------------------------
# DatumReferenceFrameRule
# ---------------------------------------------------------------------------


class TestDatumReferenceFrameRule:
    rule = DatumReferenceFrameRule()

    def test_no_datums_produces_critical(self):
        """A model with no datums at all must produce a CRITICAL issue."""
        model = GeometricModel()
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "MISSING_DATUM_REFERENCE_FRAME"
        assert issue.corrective_action
        assert issue.standard_reference
        assert "ASME Y14.5" in issue.standard_reference

    def test_no_datums_corrective_action_and_standard_reference_present(self):
        """CRITICAL issue must carry non-empty corrective_action and standard_reference."""
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues[0].corrective_action
        assert issues[0].standard_reference

    def test_only_primary_datum_produces_warning(self):
        """A model with only one datum label should produce a WARNING."""
        model = GeometricModel(datums=[_datum("A")])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.WARNING
        assert issue.issue_type == "INCOMPLETE_DATUM_REFERENCE_FRAME"

    def test_two_datums_produces_no_issues(self):
        """Two datum labels (primary + secondary) is sufficient — no WARNING."""
        model = GeometricModel(datums=[_datum("A"), _datum("B", "F2")])
        issues = self.rule.check(model)
        assert issues == []

    def test_three_datums_produces_no_issues(self):
        """A complete DRF with three distinct datum labels produces no issues."""
        model = GeometricModel(
            datums=[_datum("A"), _datum("B", "F2"), _datum("C", "F3")]
        )
        issues = self.rule.check(model)
        assert issues == []

    def test_empty_model_produces_critical(self):
        """An empty model has no datums, so it must produce a CRITICAL issue."""
        model = GeometricModel()
        issues = self.rule.check(model)
        assert any(i.severity == Severity.CRITICAL for i in issues)

    def test_rule_id_is_correct(self):
        assert self.rule.rule_id == "DATUM_REFERENCE_FRAME_RULE"

    def test_multiple_datums_with_same_label_counts_as_one(self):
        """Duplicate datum labels should not inflate the distinct-label count."""
        model = GeometricModel(
            datums=[_datum("A"), _datum("A", "F2")]  # same label twice
        )
        issues = self.rule.check(model)
        # Only one distinct label → WARNING
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING


# ---------------------------------------------------------------------------
# FeatureOrientationRule
# ---------------------------------------------------------------------------


class TestFeatureOrientationRule:
    rule = FeatureOrientationRule()

    def test_feature_with_no_dimensions_and_no_fcfs_produces_critical(self):
        """A feature with no dimensions and no FCFs has unconstrained DOF → CRITICAL."""
        feature = _feature("F1", dims=[], fcfs=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "UNCONSTRAINED_FEATURE_ORIENTATION"
        assert "F1" in issue.description
        assert issue.corrective_action
        assert issue.standard_reference
        assert "ASME Y14.5" in issue.standard_reference

    def test_feature_with_dimensions_produces_no_issue(self):
        """A feature that has at least one dimension is considered constrained."""
        feature = _feature("F1", dims=[_dim("D1")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_with_only_fcfs_produces_no_issue(self):
        """A feature with a feature control frame (but no dimensions) is constrained."""
        feature = _feature("F1", dims=[], fcfs=[_fcf("FCF1")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_with_both_dimensions_and_fcfs_produces_no_issue(self):
        """A feature with both dimensions and FCFs is fully constrained."""
        feature = _feature("F1", dims=[_dim("D1")], fcfs=[_fcf("FCF1")])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert issues == []

    def test_multiple_unconstrained_features_each_produce_critical(self):
        """Each unconstrained feature produces its own CRITICAL issue."""
        features = [_feature(f"F{i}", dims=[], fcfs=[]) for i in range(3)]
        model = GeometricModel(features=features)
        issues = self.rule.check(model)
        assert len(issues) == 3
        for issue in issues:
            assert issue.severity == Severity.CRITICAL

    def test_empty_model_produces_no_issues(self):
        """No features → no issues."""
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_issue_description_includes_feature_location(self):
        """The issue description should reference the feature's location."""
        feature = _feature("F1", dims=[], fcfs=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert "FRONT" in issues[0].description  # view_name from _loc()

    def test_rule_id_is_correct(self):
        assert self.rule.rule_id == "FEATURE_ORIENTATION_RULE"

    def test_corrective_action_references_feature_id(self):
        """The corrective action should mention the specific feature ID."""
        feature = _feature("MY_FEATURE_42", dims=[], fcfs=[])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert "MY_FEATURE_42" in issues[0].corrective_action


# ---------------------------------------------------------------------------
# GDTDatumReferenceRule
# ---------------------------------------------------------------------------


class TestGDTDatumReferenceRule:
    rule = GDTDatumReferenceRule()

    def test_fcf_referencing_undefined_datum_produces_critical(self):
        """A top-level FCF referencing a datum label not in model.datums → CRITICAL."""
        fcf = _fcf("FCF1", datum_refs=["X"])  # "X" is not defined
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        issue = issues[0]
        assert issue.severity == Severity.CRITICAL
        assert issue.issue_type == "UNDEFINED_DATUM_REFERENCE"
        assert "FCF1" in issue.description
        assert "X" in issue.description
        assert issue.corrective_action
        assert issue.standard_reference
        assert "ASME Y14.5" in issue.standard_reference

    def test_fcf_referencing_defined_datum_produces_no_issue(self):
        """A FCF referencing a datum that exists in model.datums → no issue."""
        datum = _datum("A")
        fcf = _fcf("FCF1", datum_refs=["A"])
        model = GeometricModel(datums=[datum], feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert issues == []

    def test_fcf_with_no_datum_references_produces_no_issue(self):
        """A FCF with an empty datum_references list has nothing to validate."""
        fcf = _fcf("FCF1", datum_refs=[])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert issues == []

    def test_fcf_on_feature_referencing_undefined_datum_produces_critical(self):
        """A FCF attached to a feature (not top-level) is also checked."""
        fcf = _fcf("FCF2", datum_refs=["Z"])  # "Z" is not defined
        feature = _feature("F1", fcfs=[fcf])
        model = GeometricModel(features=[feature])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.CRITICAL
        assert "FCF2" in issues[0].description
        assert "Z" in issues[0].description

    def test_fcf_on_feature_referencing_defined_datum_produces_no_issue(self):
        """A FCF on a feature referencing a defined datum → no issue."""
        datum = _datum("B")
        fcf = _fcf("FCF2", datum_refs=["B"])
        feature = _feature("F1", fcfs=[fcf])
        model = GeometricModel(features=[feature], datums=[datum])
        issues = self.rule.check(model)
        assert issues == []

    def test_multiple_undefined_datum_refs_in_one_fcf_produce_multiple_issues(self):
        """Each undefined datum reference in a FCF produces its own CRITICAL issue."""
        fcf = _fcf("FCF1", datum_refs=["X", "Y", "Z"])  # none defined
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 3
        for issue in issues:
            assert issue.severity == Severity.CRITICAL

    def test_mixed_defined_and_undefined_datum_refs(self):
        """Only undefined datum references produce issues; defined ones do not."""
        datum = _datum("A")
        fcf = _fcf("FCF1", datum_refs=["A", "B"])  # "A" defined, "B" not
        model = GeometricModel(datums=[datum], feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert "B" in issues[0].description

    def test_empty_model_produces_no_issues(self):
        """No FCFs → no issues."""
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_rule_id_is_correct(self):
        assert self.rule.rule_id == "GDT_DATUM_REFERENCE_RULE"

    def test_corrective_action_references_datum_label(self):
        """The corrective action should mention the undefined datum label."""
        fcf = _fcf("FCF1", datum_refs=["UNDEFINED_DATUM"])
        model = GeometricModel(feature_control_frames=[fcf])
        issues = self.rule.check(model)
        assert "UNDEFINED_DATUM" in issues[0].corrective_action

    def test_top_level_and_feature_fcfs_not_double_counted(self):
        """A FCF that appears in both top-level and feature lists is checked once."""
        datum = _datum("A")
        fcf = _fcf("FCF1", datum_refs=["A"])
        feature = _feature("F1", fcfs=[fcf])
        # Same FCF object in both top-level and feature
        model = GeometricModel(
            features=[feature],
            datums=[datum],
            feature_control_frames=[fcf],
        )
        issues = self.rule.check(model)
        assert issues == []
