"""Property-based tests for issue severity rules.

# Feature: engineering-drawing-analyzer

## Property 2: Missing Required Dimension Produces Critical Issue
For any GeometricModel containing a Feature that lacks a required dimension
(size dimension for any feature, position dimension for any feature, or angular
dimension for any feature with is_angular == True), the rule engine SHALL
produce at least one Issue with severity == Severity.CRITICAL whose location
references that feature.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.7, 2.8**

## Property 3: Over-Dimension Detection Produces Warning
For any GeometricModel in which a Feature has two or more Dimension objects
that specify the same geometric property (conflicting dimensions), the rule
engine SHALL produce at least one Issue with severity == Severity.WARNING
referencing those conflicting dimensions.

**Validates: Requirements 2.5, 2.6**
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
# Hypothesis strategies
# ---------------------------------------------------------------------------

st_point = st.builds(Point2D, x=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
                     y=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False))

st_location = st.builds(
    LocationReference,
    view_name=st.sampled_from(["FRONT", "TOP", "RIGHT", "SECTION A-A"]),
    coordinates=st.one_of(st.none(), st_point),
    label=st.one_of(st.none(), st.text(min_size=1, max_size=20)),
)

st_tolerance = st.builds(
    Tolerance,
    upper=st.floats(min_value=0.001, max_value=10.0, allow_nan=False),
    lower=st.floats(min_value=-10.0, max_value=-0.001, allow_nan=False),
    is_general=st.booleans(),
)

# Size dimension units (LINEAR is the default; also include named size types)
_SIZE_UNITS = ["mm", "in", "LINEAR", "DIAMETER", "RADIAL", "RADIUS", "ORDINATE"]
_ANGULAR_UNITS = ["ANGULAR", "ANGULAR_3P", "ANGLE"]

st_size_dim = st.builds(
    Dimension,
    id=st.uuids().map(str),
    value=st.floats(min_value=0.001, max_value=1000.0, allow_nan=False),
    unit=st.sampled_from(_SIZE_UNITS),
    tolerance=st.one_of(st.none(), st_tolerance),
    location=st_location,
    associated_feature_ids=st.just([]),
)

st_angular_dim = st.builds(
    Dimension,
    id=st.uuids().map(str),
    value=st.floats(min_value=0.1, max_value=179.9, allow_nan=False),
    unit=st.sampled_from(_ANGULAR_UNITS),
    tolerance=st.one_of(st.none(), st_tolerance),
    location=st_location,
    associated_feature_ids=st.just([]),
)


def _make_feature_no_size_dim() -> Feature:
    """A feature with no size dimension (only angular or empty)."""
    return Feature(
        id=str(uuid.uuid4()),
        feature_type="SLOT",
        dimensions=[],
        location=LocationReference(view_name="FRONT", coordinates=None, label=None),
        is_angular=False,
    )


def _make_angular_feature_no_angular_dim() -> Feature:
    """An angular feature with only a size dimension (no angular dim)."""
    size_dim = Dimension(
        id=str(uuid.uuid4()),
        value=10.0,
        unit="mm",
        tolerance=None,
        location=LocationReference(view_name="FRONT", coordinates=None, label=None),
        associated_feature_ids=[],
    )
    return Feature(
        id=str(uuid.uuid4()),
        feature_type="CHAMFER",
        dimensions=[size_dim],
        location=LocationReference(view_name="FRONT", coordinates=None, label=None),
        is_angular=True,
    )


def _make_feature_with_conflicting_dims() -> Feature:
    """A feature with two LINEAR dimensions (conflicting)."""
    dims = [
        Dimension(
            id=str(uuid.uuid4()),
            value=v,
            unit="mm",
            tolerance=None,
            location=LocationReference(view_name="FRONT", coordinates=None, label=None),
            associated_feature_ids=[],
        )
        for v in [10.0, 15.0]
    ]
    return Feature(
        id=str(uuid.uuid4()),
        feature_type="SLOT",
        dimensions=dims,
        location=LocationReference(view_name="FRONT", coordinates=None, label=None),
        is_angular=False,
    )


# ---------------------------------------------------------------------------
# Property 2: Missing Required Dimension Produces Critical Issue
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    extra_features=st.lists(
        st.builds(
            Feature,
            id=st.uuids().map(str),
            feature_type=st.sampled_from(["HOLE", "SLOT", "SURFACE", "EDGE"]),
            dimensions=st.lists(st_size_dim, min_size=1, max_size=3),
            feature_control_frames=st.just([]),
            location=st.one_of(st.none(), st_location),
            is_angular=st.just(False),
            is_threaded=st.booleans(),
            is_blind_hole=st.booleans(),
            ml_confidence=st.none(),
            ml_symbol_type=st.none(),
        ),
        min_size=0,
        max_size=5,
    )
)
def test_property2_missing_size_dimension_produces_critical(extra_features):
    """Property 2 (size): a feature with no size dimension → at least one CRITICAL issue."""
    bad_feature = _make_feature_no_size_dim()
    model = GeometricModel(features=[bad_feature] + extra_features)

    rule = SizeDimensionRule()
    issues = rule.check(model)

    critical_for_bad = [
        i for i in issues
        if i.severity == Severity.CRITICAL and bad_feature.id in i.description
    ]
    assert len(critical_for_bad) >= 1, (
        f"Expected at least one CRITICAL issue for feature {bad_feature.id!r}, "
        f"got issues: {issues}"
    )


@settings(max_examples=100)
@given(
    extra_features=st.lists(
        st.builds(
            Feature,
            id=st.uuids().map(str),
            feature_type=st.sampled_from(["HOLE", "SLOT", "SURFACE"]),
            dimensions=st.lists(st_size_dim, min_size=1, max_size=3),
            feature_control_frames=st.just([]),
            location=st.one_of(st.none(), st_location),
            is_angular=st.just(True),
            is_threaded=st.booleans(),
            is_blind_hole=st.booleans(),
            ml_confidence=st.none(),
            ml_symbol_type=st.none(),
        ),
        min_size=0,
        max_size=5,
    )
)
def test_property2_missing_angular_dimension_produces_critical(extra_features):
    """Property 2 (angular): an angular feature with no angular dim → at least one CRITICAL issue."""
    bad_feature = _make_angular_feature_no_angular_dim()
    model = GeometricModel(features=[bad_feature] + extra_features)

    rule = AngularDimensionRule()
    issues = rule.check(model)

    critical_for_bad = [
        i for i in issues
        if i.severity == Severity.CRITICAL and bad_feature.id in i.description
    ]
    assert len(critical_for_bad) >= 1, (
        f"Expected at least one CRITICAL issue for angular feature {bad_feature.id!r}, "
        f"got issues: {issues}"
    )


@settings(max_examples=100)
@given(
    extra_features=st.lists(
        st.builds(
            Feature,
            id=st.uuids().map(str),
            feature_type=st.sampled_from(["HOLE", "SLOT", "SURFACE"]),
            dimensions=st.lists(st_size_dim, min_size=1, max_size=3),
            feature_control_frames=st.just([]),
            location=st.one_of(st.none(), st_location),
            is_angular=st.just(False),
            is_threaded=st.booleans(),
            is_blind_hole=st.booleans(),
            ml_confidence=st.none(),
            ml_symbol_type=st.none(),
        ),
        min_size=0,
        max_size=5,
    )
)
def test_property2_missing_position_dimension_produces_critical(extra_features):
    """Property 2 (position): a feature with no position dim and no datum → CRITICAL issue."""
    # A feature with only an angular dimension has no position info.
    ang_only_dim = Dimension(
        id=str(uuid.uuid4()),
        value=45.0,
        unit="ANGULAR",
        tolerance=None,
        location=LocationReference(view_name="FRONT", coordinates=None, label=None),
        associated_feature_ids=[],
    )
    bad_feature = Feature(
        id=str(uuid.uuid4()),
        feature_type="CHAMFER",
        dimensions=[ang_only_dim],
        location=LocationReference(view_name="FRONT", coordinates=None, label=None),
        is_angular=True,
    )
    model = GeometricModel(features=[bad_feature] + extra_features)

    rule = PositionDimensionRule()
    issues = rule.check(model)

    critical_for_bad = [
        i for i in issues
        if i.severity == Severity.CRITICAL and bad_feature.id in i.description
    ]
    assert len(critical_for_bad) >= 1, (
        f"Expected at least one CRITICAL issue for feature {bad_feature.id!r}, "
        f"got issues: {issues}"
    )


# ---------------------------------------------------------------------------
# Property 3: Over-Dimension Detection Produces Warning
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    extra_features=st.lists(
        st.builds(
            Feature,
            id=st.uuids().map(str),
            feature_type=st.sampled_from(["HOLE", "SLOT", "SURFACE"]),
            dimensions=st.lists(st_size_dim, min_size=1, max_size=1),
            feature_control_frames=st.just([]),
            location=st.one_of(st.none(), st_location),
            is_angular=st.just(False),
            is_threaded=st.booleans(),
            is_blind_hole=st.booleans(),
            ml_confidence=st.none(),
            ml_symbol_type=st.none(),
        ),
        min_size=0,
        max_size=5,
    )
)
def test_property3_conflicting_dimensions_produce_warning(extra_features):
    """Property 3: a feature with two conflicting dimensions → at least one WARNING issue."""
    bad_feature = _make_feature_with_conflicting_dims()
    model = GeometricModel(features=[bad_feature] + extra_features)

    rule = OverDimensionRule()
    issues = rule.check(model)

    warning_for_bad = [
        i for i in issues
        if i.severity == Severity.WARNING and bad_feature.id in i.description
    ]
    assert len(warning_for_bad) >= 1, (
        f"Expected at least one WARNING issue for feature {bad_feature.id!r}, "
        f"got issues: {issues}"
    )


@settings(max_examples=100)
@given(
    n_extra_dims=st.integers(min_value=1, max_value=5),
    base_value=st.floats(min_value=1.0, max_value=100.0, allow_nan=False),
)
def test_property3_redundant_same_value_dimensions_produce_warning(n_extra_dims, base_value):
    """Property 3: even identical redundant dimensions on the same feature → WARNING."""
    dims = [
        Dimension(
            id=str(uuid.uuid4()),
            value=base_value,
            unit="mm",
            tolerance=None,
            location=LocationReference(view_name="FRONT", coordinates=None, label=None),
            associated_feature_ids=[],
        )
        for _ in range(n_extra_dims + 1)  # at least 2 dims
    ]
    feature = Feature(
        id=str(uuid.uuid4()),
        feature_type="SLOT",
        dimensions=dims,
        location=LocationReference(view_name="FRONT", coordinates=None, label=None),
    )
    model = GeometricModel(features=[feature])

    rule = OverDimensionRule()
    issues = rule.check(model)

    warning_issues = [i for i in issues if i.severity == Severity.WARNING]
    assert len(warning_issues) >= 1, (
        f"Expected at least one WARNING for {n_extra_dims + 1} redundant dims, "
        f"got: {issues}"
    )
