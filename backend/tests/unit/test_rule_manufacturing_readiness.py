"""Unit tests for the manufacturing_readiness rule module.

Tests cover concrete fixtures for each of the five rules:
- TitleBlockRule
- SurfaceFinishRule
- HoleSpecificationRule
- ViewSufficiencyRule
- NoteContradictionRule
"""

import pytest

from engineering_drawing_analyzer.models import (
    Dimension,
    Feature,
    GeometricModel,
    LocationReference,
    Point2D,
    Severity,
    TitleBlock,
    Tolerance,
    View,
)
from engineering_drawing_analyzer.rule_engine.manufacturing_readiness import (
    HoleSpecificationRule,
    NoteContradictionRule,
    SurfaceFinishRule,
    TitleBlockRule,
    ViewSufficiencyRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _loc(view: str = "FRONT") -> LocationReference:
    return LocationReference(view_name=view, coordinates=Point2D(0.0, 0.0), label=None)


def _tol(upper: float = 0.1, lower: float = -0.1) -> Tolerance:
    return Tolerance(upper=upper, lower=lower)


def _dim(
    id: str,
    value: float = 10.0,
    unit: str = "mm",
    tolerance: Tolerance | None = None,
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


def _feature(
    id: str,
    feature_type: str = "HOLE",
    dims: list[Dimension] | None = None,
    is_blind_hole: bool = False,
    is_threaded: bool = False,
) -> Feature:
    return Feature(
        id=id,
        feature_type=feature_type,
        dimensions=dims or [],
        location=_loc(),
        is_blind_hole=is_blind_hole,
        is_threaded=is_threaded,
    )


def _full_title_block() -> TitleBlock:
    return TitleBlock(
        part_number="PN-001",
        revision="A",
        material="STEEL",
        scale="1:1",
        units="mm",
    )


# ---------------------------------------------------------------------------
# TitleBlockRule
# ---------------------------------------------------------------------------


class TestTitleBlockRule:
    rule = TitleBlockRule()

    def test_complete_title_block_passes(self):
        model = GeometricModel(title_block=_full_title_block())
        issues = self.rule.check(model)
        assert issues == []

    def test_no_title_block_produces_five_critical_issues(self):
        model = GeometricModel(title_block=None)
        issues = self.rule.check(model)
        assert len(issues) == 5
        for issue in issues:
            assert issue.severity == Severity.CRITICAL

    def test_missing_part_number_produces_one_critical_issue(self):
        tb = TitleBlock(part_number=None, revision="A", material="STEEL", scale="1:1", units="mm")
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_TITLE_BLOCK_PART_NUMBER"
        assert issues[0].severity == Severity.CRITICAL

    def test_missing_revision_produces_one_critical_issue(self):
        tb = TitleBlock(part_number="PN-001", revision=None, material="STEEL", scale="1:1", units="mm")
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_TITLE_BLOCK_REVISION"

    def test_missing_material_produces_one_critical_issue(self):
        tb = TitleBlock(part_number="PN-001", revision="A", material=None, scale="1:1", units="mm")
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_TITLE_BLOCK_MATERIAL"

    def test_missing_scale_produces_one_critical_issue(self):
        tb = TitleBlock(part_number="PN-001", revision="A", material="STEEL", scale=None, units="mm")
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_TITLE_BLOCK_SCALE"

    def test_missing_units_produces_one_critical_issue(self):
        tb = TitleBlock(part_number="PN-001", revision="A", material="STEEL", scale="1:1", units=None)
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_TITLE_BLOCK_UNITS"

    def test_multiple_missing_fields_produce_one_issue_each(self):
        tb = TitleBlock(part_number=None, revision=None, material="STEEL", scale="1:1", units="mm")
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 2
        issue_types = {i.issue_type for i in issues}
        assert "MISSING_TITLE_BLOCK_PART_NUMBER" in issue_types
        assert "MISSING_TITLE_BLOCK_REVISION" in issue_types

    def test_all_five_fields_missing_produce_exactly_five_issues(self):
        tb = TitleBlock(part_number=None, revision=None, material=None, scale=None, units=None)
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 5

    def test_no_duplicate_issues_for_same_field(self):
        """Each missing field produces exactly one issue — no duplicates."""
        tb = TitleBlock(part_number=None, revision="A", material="STEEL", scale="1:1", units="mm")
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 1

    def test_critical_issues_have_corrective_action_and_standard_reference(self):
        tb = TitleBlock(part_number=None, revision=None, material=None, scale=None, units=None)
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        for issue in issues:
            assert issue.corrective_action, f"Issue {issue.issue_type} missing corrective_action"
            assert issue.standard_reference, f"Issue {issue.issue_type} missing standard_reference"

    def test_empty_string_part_number_treated_as_missing(self):
        tb = TitleBlock(part_number="", revision="A", material="STEEL", scale="1:1", units="mm")
        model = GeometricModel(title_block=tb)
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "MISSING_TITLE_BLOCK_PART_NUMBER"


# ---------------------------------------------------------------------------
# SurfaceFinishRule
# ---------------------------------------------------------------------------


class TestSurfaceFinishRule:
    rule = SurfaceFinishRule()

    def test_no_surface_features_produces_no_issues(self):
        hole = _feature("H1", feature_type="HOLE")
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        assert issues == []

    def test_surface_with_finish_note_referencing_feature_passes(self):
        surface = _feature("S1", feature_type="SURFACE")
        model = GeometricModel(
            features=[surface],
            notes=["S1: Ra 1.6 µm finish required"],
        )
        issues = self.rule.check(model)
        assert issues == []

    def test_surface_with_general_finish_note_passes(self):
        surface = _feature("S1", feature_type="SURFACE")
        model = GeometricModel(
            features=[surface],
            notes=["ALL MACHINED SURFACES: Ra 3.2"],
        )
        issues = self.rule.check(model)
        assert issues == []

    def test_surface_with_finish_keyword_in_dimension_unit_passes(self):
        dim = _dim("D1", unit="Ra")
        surface = _feature("S1", feature_type="SURFACE", dims=[dim])
        model = GeometricModel(features=[surface])
        issues = self.rule.check(model)
        assert issues == []

    def test_surface_without_finish_callout_produces_warning(self):
        surface = _feature("S1", feature_type="SURFACE")
        model = GeometricModel(features=[surface])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].severity == Severity.WARNING
        assert issues[0].issue_type == "MISSING_SURFACE_FINISH_CALLOUT"
        assert "S1" in issues[0].description

    def test_multiple_surfaces_without_finish_produce_one_warning_each(self):
        surfaces = [_feature(f"S{i}", feature_type="SURFACE") for i in range(3)]
        model = GeometricModel(features=surfaces)
        issues = self.rule.check(model)
        assert len(issues) == 3
        for issue in issues:
            assert issue.severity == Severity.WARNING

    def test_surface_with_roughness_note_passes(self):
        surface = _feature("S1", feature_type="SURFACE")
        model = GeometricModel(
            features=[surface],
            notes=["SURFACE ROUGHNESS: Rz 6.3"],
        )
        issues = self.rule.check(model)
        assert issues == []

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []


# ---------------------------------------------------------------------------
# HoleSpecificationRule
# ---------------------------------------------------------------------------


class TestHoleSpecificationRule:
    rule = HoleSpecificationRule()

    def test_complete_hole_passes(self):
        """A hole with diameter, tolerance, and no special flags passes."""
        dim = _dim("D1", value=10.0, unit="mm", tolerance=_tol())
        hole = _feature("H1", feature_type="HOLE", dims=[dim])
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        assert issues == []

    def test_hole_without_dimensions_produces_critical(self):
        hole = _feature("H1", feature_type="HOLE", dims=[])
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        diameter_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_DIAMETER"]
        assert len(diameter_issues) == 1
        assert diameter_issues[0].severity == Severity.CRITICAL

    def test_blind_hole_without_depth_produces_critical(self):
        dim = _dim("D1", value=10.0, unit="mm", tolerance=_tol())
        hole = _feature("H1", feature_type="HOLE", dims=[dim], is_blind_hole=True)
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        depth_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_DEPTH"]
        assert len(depth_issues) == 1
        assert depth_issues[0].severity == Severity.CRITICAL

    def test_blind_hole_with_depth_note_passes(self):
        dim = _dim("D1", value=10.0, unit="mm", tolerance=_tol())
        hole = _feature("H1", feature_type="HOLE", dims=[dim], is_blind_hole=True)
        model = GeometricModel(
            features=[hole],
            notes=["H1: 10mm DEEP"],
        )
        issues = self.rule.check(model)
        depth_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_DEPTH"]
        assert depth_issues == []

    def test_blind_hole_with_depth_unit_passes(self):
        dim_dia = _dim("D1", value=10.0, unit="mm", tolerance=_tol())
        dim_depth = _dim("D2", value=15.0, unit="DEPTH")
        hole = _feature("H1", feature_type="HOLE", dims=[dim_dia, dim_depth], is_blind_hole=True)
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        depth_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_DEPTH"]
        assert depth_issues == []

    def test_hole_without_tolerance_produces_critical(self):
        dim = _dim("D1", value=10.0, unit="mm", tolerance=None)
        hole = _feature("H1", feature_type="HOLE", dims=[dim])
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        tol_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_TOLERANCE"]
        assert len(tol_issues) == 1
        assert tol_issues[0].severity == Severity.CRITICAL

    def test_threaded_hole_without_thread_note_produces_critical(self):
        dim = _dim("D1", value=6.0, unit="mm", tolerance=_tol())
        hole = _feature("H1", feature_type="HOLE", dims=[dim], is_threaded=True)
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        thread_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_THREAD_SPEC"]
        assert len(thread_issues) == 1
        assert thread_issues[0].severity == Severity.CRITICAL

    def test_threaded_hole_with_thread_note_passes(self):
        dim = _dim("D1", value=6.0, unit="mm", tolerance=_tol())
        hole = _feature("H1", feature_type="HOLE", dims=[dim], is_threaded=True)
        model = GeometricModel(
            features=[hole],
            notes=["M6x1.0-6H THREAD"],
        )
        issues = self.rule.check(model)
        thread_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_THREAD_SPEC"]
        assert thread_issues == []

    def test_non_hole_features_are_ignored(self):
        slot = _feature("SL1", feature_type="SLOT", dims=[])
        model = GeometricModel(features=[slot])
        issues = self.rule.check(model)
        assert issues == []

    def test_critical_issues_have_corrective_action_and_standard_reference(self):
        hole = _feature("H1", feature_type="HOLE", dims=[])
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        for issue in issues:
            if issue.severity == Severity.CRITICAL:
                assert issue.corrective_action
                assert issue.standard_reference

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_hole_with_tolerance_passes_tolerance_check(self):
        dim = _dim("D1", value=10.0, unit="mm", tolerance=_tol(0.05, -0.05))
        hole = _feature("H1", feature_type="HOLE", dims=[dim])
        model = GeometricModel(features=[hole])
        issues = self.rule.check(model)
        tol_issues = [i for i in issues if i.issue_type == "HOLE_MISSING_TOLERANCE"]
        assert tol_issues == []


# ---------------------------------------------------------------------------
# ViewSufficiencyRule
# ---------------------------------------------------------------------------


class TestViewSufficiencyRule:
    rule = ViewSufficiencyRule()

    def test_all_features_in_views_passes(self):
        feature = _feature("F1")
        view = View(name="FRONT", features=["F1"])
        model = GeometricModel(features=[feature], views=[view])
        issues = self.rule.check(model)
        assert issues == []

    def test_no_views_with_features_produces_critical(self):
        feature = _feature("F1")
        model = GeometricModel(features=[feature], views=[])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "NO_ORTHOGRAPHIC_VIEWS"
        assert issues[0].severity == Severity.CRITICAL

    def test_no_views_no_features_produces_no_issues(self):
        model = GeometricModel(features=[], views=[])
        issues = self.rule.check(model)
        assert issues == []

    def test_feature_not_in_any_view_produces_critical(self):
        f1 = _feature("F1")
        f2 = _feature("F2")
        view = View(name="FRONT", features=["F1"])
        model = GeometricModel(features=[f1, f2], views=[view])
        issues = self.rule.check(model)
        assert len(issues) == 1
        assert issues[0].issue_type == "FEATURE_NOT_IN_ANY_VIEW"
        assert "F2" in issues[0].description
        assert issues[0].severity == Severity.CRITICAL

    def test_feature_in_multiple_views_passes(self):
        feature = _feature("F1")
        view1 = View(name="FRONT", features=["F1"])
        view2 = View(name="TOP", features=["F1"])
        model = GeometricModel(features=[feature], views=[view1, view2])
        issues = self.rule.check(model)
        assert issues == []

    def test_multiple_features_not_in_views_produce_one_issue_each(self):
        features = [_feature(f"F{i}") for i in range(3)]
        view = View(name="FRONT", features=[])
        model = GeometricModel(features=features, views=[view])
        issues = self.rule.check(model)
        assert len(issues) == 3
        for issue in issues:
            assert issue.issue_type == "FEATURE_NOT_IN_ANY_VIEW"

    def test_critical_issues_have_corrective_action_and_standard_reference(self):
        feature = _feature("F1")
        model = GeometricModel(features=[feature], views=[])
        issues = self.rule.check(model)
        for issue in issues:
            if issue.severity == Severity.CRITICAL:
                assert issue.corrective_action
                assert issue.standard_reference

    def test_empty_model_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []


# ---------------------------------------------------------------------------
# NoteContradictionRule
# ---------------------------------------------------------------------------


class TestNoteContradictionRule:
    rule = NoteContradictionRule()

    def test_no_notes_produces_no_issues(self):
        model = GeometricModel()
        issues = self.rule.check(model)
        assert issues == []

    def test_note_matching_dimension_value_passes(self):
        dim = _dim("D1", value=10.0, unit="mm", feature_ids=["F1"])
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(
            features=[feature],
            notes=["F1: dimension is 10.0 mm"],
        )
        issues = self.rule.check(model)
        contradiction_issues = [
            i for i in issues if i.issue_type == "NOTE_DIMENSION_CONTRADICTION"
        ]
        assert contradiction_issues == []

    def test_note_contradicting_dimension_value_produces_critical(self):
        dim = _dim("D1", value=10.0, unit="mm", feature_ids=["F1"])
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(
            features=[feature],
            notes=["F1: dimension is 15.0 mm"],
        )
        issues = self.rule.check(model)
        contradiction_issues = [
            i for i in issues if i.issue_type == "NOTE_DIMENSION_CONTRADICTION"
        ]
        assert len(contradiction_issues) == 1
        assert contradiction_issues[0].severity == Severity.CRITICAL

    def test_metric_and_imperial_notes_produce_critical(self):
        model = GeometricModel(
            notes=[
                "ALL DIMENSIONS IN MM",
                "ALL DIMENSIONS IN INCHES",
            ]
        )
        issues = self.rule.check(model)
        unit_issues = [i for i in issues if i.issue_type == "NOTE_UNIT_SYSTEM_CONTRADICTION"]
        assert len(unit_issues) == 1
        assert unit_issues[0].severity == Severity.CRITICAL

    def test_two_metric_notes_produce_no_contradiction(self):
        model = GeometricModel(
            notes=[
                "ALL DIMENSIONS IN MM",
                "METRIC UNITS APPLY",
            ]
        )
        issues = self.rule.check(model)
        unit_issues = [i for i in issues if i.issue_type == "NOTE_UNIT_SYSTEM_CONTRADICTION"]
        assert unit_issues == []

    def test_note_without_numbers_produces_no_contradiction(self):
        dim = _dim("D1", value=10.0, unit="mm", feature_ids=["F1"])
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(
            features=[feature],
            notes=["F1: see detail view for specifications"],
        )
        issues = self.rule.check(model)
        contradiction_issues = [
            i for i in issues if i.issue_type == "NOTE_DIMENSION_CONTRADICTION"
        ]
        assert contradiction_issues == []

    def test_note_not_referencing_any_feature_produces_no_contradiction(self):
        dim = _dim("D1", value=10.0, unit="mm", feature_ids=["F1"])
        feature = _feature("F1", dims=[dim])
        model = GeometricModel(
            features=[feature],
            notes=["GENERAL NOTE: all radii 2.0 mm unless otherwise specified"],
        )
        issues = self.rule.check(model)
        contradiction_issues = [
            i for i in issues if i.issue_type == "NOTE_DIMENSION_CONTRADICTION"
        ]
        assert contradiction_issues == []

    def test_critical_issues_have_corrective_action_and_standard_reference(self):
        model = GeometricModel(
            notes=[
                "ALL DIMENSIONS IN MM",
                "ALL DIMENSIONS IN INCHES",
            ]
        )
        issues = self.rule.check(model)
        for issue in issues:
            if issue.severity == Severity.CRITICAL:
                assert issue.corrective_action
                assert issue.standard_reference

    def test_empty_notes_list_produces_no_issues(self):
        model = GeometricModel(notes=[])
        issues = self.rule.check(model)
        assert issues == []
