"""Dimension completeness verification rules.

This module implements the four rules that check whether every feature on a
drawing is fully dimensioned:

* ``SizeDimensionRule``     — every feature must have at least one size dimension.
* ``PositionDimensionRule`` — every feature's position must be dimensioned
                              relative to a datum or a fully-dimensioned feature.
* ``OverDimensionRule``     — conflicting (redundant) dimensions on the same
                              feature are flagged as a warning.
* ``AngularDimensionRule``  — angular features must carry an angular dimension.

All ``CRITICAL`` issues include a non-empty ``corrective_action`` and a
``standard_reference`` pointing to the applicable ASME Y14.5-2018 clause.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Optional

from ..models import (
    Dimension,
    Feature,
    GeometricModel,
    Issue,
    LocationReference,
    Severity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Dimension types that convey size information (linear, radial, diameter, etc.)
_SIZE_DIMENSION_TYPES: frozenset[str] = frozenset(
    {
        "LINEAR",
        "ALIGNED",
        "RADIAL",
        "DIAMETER",
        "RADIUS",
        "ORDINATE",
        "ARC_LENGTH",
        "SIZE",
    }
)

# Dimension types that convey angular information
_ANGULAR_DIMENSION_TYPES: frozenset[str] = frozenset(
    {
        "ANGULAR",
        "ANGULAR_3P",
        "ANGLE",
    }
)

# Dimension types that convey positional information (coordinates, ordinate, etc.)
_POSITION_DIMENSION_TYPES: frozenset[str] = frozenset(
    {
        "LINEAR",
        "ALIGNED",
        "ORDINATE",
        "COORDINATE",
        "POSITION",
    }
)


def _feature_location(feature: Feature) -> LocationReference:
    """Return the feature's location, or a generic placeholder if absent."""
    if feature.location is not None:
        return feature.location
    return LocationReference(
        view_name="UNKNOWN",
        coordinates=None,
        label=feature.id,
    )


def _dim_type(dim: Dimension) -> str:
    """Derive a normalised dimension type string from a ``Dimension`` object.

    The ``Dimension`` dataclass does not carry an explicit ``dim_type`` field in
    the current model, so we infer the type from the ``unit`` field and the
    ``associated_feature_ids`` list as a best-effort heuristic.  Rules that need
    a richer type signal should be extended once the parser populates a
    ``dim_type`` attribute.

    For now we store the type in the ``unit`` field when it is one of the
    recognised type tokens (e.g. ``"ANGULAR"``), otherwise we fall back to
    ``"LINEAR"`` as the default size-dimension type.
    """
    # Allow parsers / tests to embed the dimension type in the unit field.
    normalised = dim.unit.upper().strip()
    if normalised in _SIZE_DIMENSION_TYPES:
        return normalised
    if normalised in _ANGULAR_DIMENSION_TYPES:
        return normalised
    if normalised in _POSITION_DIMENSION_TYPES:
        return normalised
    # Default: treat any numeric dimension as a linear size dimension.
    return "LINEAR"


def _is_size_dimension(dim: Dimension) -> bool:
    return _dim_type(dim) in _SIZE_DIMENSION_TYPES


def _is_angular_dimension(dim: Dimension) -> bool:
    return _dim_type(dim) in _ANGULAR_DIMENSION_TYPES


def _is_position_dimension(dim: Dimension) -> bool:
    return _dim_type(dim) in _POSITION_DIMENSION_TYPES


# ---------------------------------------------------------------------------
# SizeDimensionRule
# ---------------------------------------------------------------------------


class SizeDimensionRule:
    """Every ``Feature`` must have at least one size ``Dimension``.

    A size dimension specifies the physical extent of a feature (length,
    diameter, radius, etc.).  Features without any size dimension cannot be
    manufactured to the correct geometry.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 §7.2 (Size Dimensions)
    """

    rule_id: str = "SIZE_DIMENSION_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``CRITICAL`` issue for each feature that lacks a size dimension."""
        issues: list[Issue] = []

        for feature in model.features:
            has_size_dim = any(_is_size_dimension(d) for d in feature.dimensions)
            if not has_size_dim:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="MISSING_SIZE_DIMENSION",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature '{feature.id}' (type: {feature.feature_type}) "
                            "has no size dimension.  Every feature must have at least "
                            "one dimension specifying its size (length, diameter, "
                            "radius, etc.)."
                        ),
                        location=_feature_location(feature),
                        corrective_action=(
                            "Add a size dimension to this feature that specifies its "
                            "physical extent (e.g. a linear dimension for a slot, a "
                            "diameter callout for a hole).  Ensure the dimension value "
                            "and unit are clearly annotated on the drawing."
                        ),
                        standard_reference="ASME Y14.5-2018 §7.2",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# PositionDimensionRule
# ---------------------------------------------------------------------------


class PositionDimensionRule:
    """Every ``Feature``'s position must be dimensioned relative to a ``Datum``
    or another fully-dimensioned feature.

    A feature whose location on the drawing is not tied to a datum or a
    reference feature is ambiguous — a machinist cannot determine where to
    place it.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 §4.1 (Datum Reference Frames) and §7.4
    """

    rule_id: str = "POSITION_DIMENSION_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``CRITICAL`` issue for each feature that lacks a position dimension."""
        issues: list[Issue] = []

        # Collect datum labels defined in the model.
        datum_labels: set[str] = {d.label for d in model.datums}

        # Collect feature IDs that have at least one size dimension (fully
        # dimensioned features can serve as position references).
        fully_dimensioned_ids: set[str] = {
            f.id
            for f in model.features
            if any(_is_size_dimension(d) for d in f.dimensions)
        }

        # Build a mapping from feature ID → all dimensions that reference it
        # (from the top-level dimension list as well as the feature's own list).
        feature_dims: dict[str, list[Dimension]] = defaultdict(list)
        for dim in model.dimensions:
            for fid in dim.associated_feature_ids:
                feature_dims[fid].append(dim)
        for feature in model.features:
            for dim in feature.dimensions:
                feature_dims[feature.id].append(dim)

        for feature in model.features:
            all_dims = feature_dims[feature.id]

            # Check 1: does the feature have a position dimension?
            has_position_dim = any(_is_position_dimension(d) for d in all_dims)

            # Check 2: is the feature referenced by a GD&T position FCF that
            # itself references a defined datum?
            has_gdt_position = any(
                fcf.gdt_symbol in {"⊕", "POSITION", "TRUE_POSITION"}
                and any(ref in datum_labels for ref in fcf.datum_references)
                for fcf in feature.feature_control_frames
            )

            # Check 3: does the feature have a datum applied directly to it?
            is_datum_feature = any(
                d.feature_id == feature.id for d in model.datums
            )

            if not (has_position_dim or has_gdt_position or is_datum_feature):
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="MISSING_POSITION_DIMENSION",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature '{feature.id}' (type: {feature.feature_type}) "
                            "has no position dimension relative to a datum or a fully "
                            "dimensioned feature.  Its location on the drawing is "
                            "undefined."
                        ),
                        location=_feature_location(feature),
                        corrective_action=(
                            "Add a position dimension that locates this feature "
                            "relative to an established datum (e.g. Datum A, B, or C) "
                            "or another fully dimensioned feature.  Alternatively, "
                            "apply a GD&T position feature control frame referencing "
                            "the datum reference frame."
                        ),
                        standard_reference="ASME Y14.5-2018 §4.1, §7.4",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# OverDimensionRule
# ---------------------------------------------------------------------------


class OverDimensionRule:
    """Detect conflicting (redundant) dimensions applied to the same feature.

    Over-dimensioning creates ambiguity: if two dimensions specify the same
    geometric property with different values, the machinist cannot determine
    which to use.  Even identical redundant dimensions are flagged because they
    violate ASME Y14.5 and can cause confusion.

    Severity: ``WARNING``
    Standard: ASME Y14.5-2018 §1.4(j) (Redundant Dimensioning)
    """

    rule_id: str = "OVER_DIMENSION_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``WARNING`` issue for each feature with conflicting dimensions."""
        issues: list[Issue] = []

        for feature in model.features:
            dims = list(feature.dimensions)

            # Also include top-level dimensions that reference this feature.
            for dim in model.dimensions:
                if feature.id in dim.associated_feature_ids and dim not in dims:
                    dims.append(dim)

            if len(dims) < 2:
                continue

            # Group dimensions by their inferred type.
            by_type: dict[str, list[Dimension]] = defaultdict(list)
            for dim in dims:
                by_type[_dim_type(dim)].append(dim)

            for dim_type, type_dims in by_type.items():
                if len(type_dims) < 2:
                    continue

                # Check for conflicting values within the same type group.
                values = [d.value for d in type_dims]
                has_conflict = len(set(values)) > 1 or len(type_dims) > 1

                if has_conflict:
                    dim_ids = ", ".join(d.id for d in type_dims)
                    dim_values = ", ".join(str(v) for v in values)
                    issues.append(
                        Issue(
                            issue_id=str(uuid.uuid4()),
                            rule_id=self.rule_id,
                            issue_type="OVER_DIMENSION",
                            severity=Severity.WARNING,
                            description=(
                                f"Feature '{feature.id}' (type: {feature.feature_type}) "
                                f"has {len(type_dims)} conflicting {dim_type} dimensions "
                                f"(IDs: {dim_ids}; values: {dim_values}).  "
                                "Redundant or conflicting dimensions create ambiguity."
                            ),
                            location=_feature_location(feature),
                            corrective_action=(
                                f"Remove the redundant {dim_type} dimension(s) from "
                                f"feature '{feature.id}'.  Each geometric property "
                                "should be dimensioned exactly once per ASME Y14.5.  "
                                "If the values differ, resolve the conflict and retain "
                                "only the authoritative dimension."
                            ),
                            standard_reference="ASME Y14.5-2018 §1.4(j)",
                        )
                    )

        return issues


# ---------------------------------------------------------------------------
# AngularDimensionRule
# ---------------------------------------------------------------------------


class AngularDimensionRule:
    """Features with ``is_angular == True`` must have an angular dimension.

    Angular features (chamfers, tapers, angled surfaces) require an explicit
    angular dimension so that the machinist knows the required angle.  Without
    it the feature geometry is undefined.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 §7.7 (Angular Dimensions)
    """

    rule_id: str = "ANGULAR_DIMENSION_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``CRITICAL`` issue for each angular feature without an angular dimension."""
        issues: list[Issue] = []

        for feature in model.features:
            if not feature.is_angular:
                continue

            # Check the feature's own dimensions and top-level dimensions that
            # reference this feature.
            all_dims = list(feature.dimensions)
            for dim in model.dimensions:
                if feature.id in dim.associated_feature_ids and dim not in all_dims:
                    all_dims.append(dim)

            has_angular_dim = any(_is_angular_dimension(d) for d in all_dims)

            if not has_angular_dim:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="MISSING_ANGULAR_DIMENSION",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature '{feature.id}' (type: {feature.feature_type}) "
                            "is marked as an angular feature (chamfer, taper, or "
                            "angled surface) but has no angular dimension.  The "
                            "required angle is undefined."
                        ),
                        location=_feature_location(feature),
                        corrective_action=(
                            "Add an angular dimension to this feature specifying the "
                            "required angle in degrees.  For chamfers, use the "
                            "standard chamfer callout format (e.g. '2 × 45°').  "
                            "For tapers and angled surfaces, dimension the included "
                            "or half-angle as appropriate."
                        ),
                        standard_reference="ASME Y14.5-2018 §7.7",
                    )
                )

        return issues
