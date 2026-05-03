"""Tolerance verification rules.

This module implements the three rules that check whether tolerances are
correctly specified on a drawing:

* ``DimensionToleranceRule``  — every ``Dimension`` must have an explicit
                                ``Tolerance`` or the model must carry a
                                drawing-level ``general_tolerance`` block.
* ``FCFCompletenessRule``     — every ``FeatureControlFrame`` must have a
                                valid ``tolerance_value`` and the required
                                datum references per ASME Y14.5.
* ``ToleranceStackUpRule``    — detect dimension chains where the arithmetic
                                sum of individual tolerances exceeds the
                                tightest (smallest) tolerance in that chain.

All ``CRITICAL`` issues include a non-empty ``corrective_action`` and a
``standard_reference`` pointing to the applicable ASME Y14.5-2018 clause.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Optional

from ..models import (
    Dimension,
    FeatureControlFrame,
    GeometricModel,
    Issue,
    LocationReference,
    Severity,
    Tolerance,
)

# ---------------------------------------------------------------------------
# GD&T symbols that require at least one datum reference per ASME Y14.5-2018.
# Symbols that define a self-contained tolerance zone (form tolerances) do NOT
# require datum references.
# ---------------------------------------------------------------------------

# Form tolerances — no datum reference required.
_FORM_TOLERANCE_SYMBOLS: frozenset[str] = frozenset(
    {
        "⏤",  # straightness
        "⏥",  # flatness
        "○",  # circularity / roundness
        "⌭",  # cylindricity
        "STRAIGHTNESS",
        "FLATNESS",
        "CIRCULARITY",
        "ROUNDNESS",
        "CYLINDRICITY",
    }
)

# Profile tolerances — datum reference optional (required only when the
# profile is related to a DRF).  We treat them as not requiring a datum
# unless the FCF already has datum references, in which case we validate them.
_PROFILE_TOLERANCE_SYMBOLS: frozenset[str] = frozenset(
    {
        "⌒",  # profile of a line
        "⌓",  # profile of a surface
        "PROFILE_OF_A_LINE",
        "PROFILE_OF_A_SURFACE",
    }
)

# Orientation, location, and runout tolerances — datum reference IS required.
_DATUM_REQUIRED_SYMBOLS: frozenset[str] = frozenset(
    {
        "∠",  # angularity
        "⊥",  # perpendicularity
        "∥",  # parallelism
        "⊕",  # position / true position
        "◎",  # concentricity / coaxiality
        "≡",  # symmetry
        "↗",  # circular runout
        "↗↗",  # total runout
        "ANGULARITY",
        "PERPENDICULARITY",
        "PARALLELISM",
        "POSITION",
        "TRUE_POSITION",
        "CONCENTRICITY",
        "COAXIALITY",
        "SYMMETRY",
        "CIRCULAR_RUNOUT",
        "TOTAL_RUNOUT",
    }
)


# ---------------------------------------------------------------------------
# DimensionToleranceRule
# ---------------------------------------------------------------------------


class DimensionToleranceRule:
    """Every ``Dimension`` must have an associated ``Tolerance``.

    A dimension without a tolerance is ambiguous — the machinist cannot
    determine the acceptable variation.  The rule is satisfied if:

    * The ``Dimension`` has an explicit ``tolerance`` (``tolerance is not None``), OR
    * The ``GeometricModel`` carries a drawing-level ``general_tolerance`` block.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 §2.1 (General Tolerancing), §2.7 (Limits and Fits)
    """

    rule_id: str = "DIMENSION_TOLERANCE_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``CRITICAL`` issue for each dimension that lacks a tolerance."""
        issues: list[Issue] = []

        # If a general tolerance block is present, all dimensions are covered.
        if model.general_tolerance is not None:
            return issues

        # Collect all dimensions: top-level + those attached to features.
        all_dimensions: list[Dimension] = list(model.dimensions)
        seen_ids: set[str] = {d.id for d in model.dimensions}
        for feature in model.features:
            for dim in feature.dimensions:
                if dim.id not in seen_ids:
                    all_dimensions.append(dim)
                    seen_ids.add(dim.id)

        for dim in all_dimensions:
            if dim.tolerance is None:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="MISSING_DIMENSION_TOLERANCE",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Dimension '{dim.id}' (value: {dim.value} {dim.unit}) "
                            "has no explicit tolerance and the drawing does not "
                            "define a general tolerance block.  Without a tolerance "
                            "the acceptable variation for this dimension is undefined, "
                            "making the drawing unmanufacturable."
                        ),
                        location=dim.location,
                        corrective_action=(
                            f"Add an explicit tolerance to dimension '{dim.id}' "
                            "(e.g. ±0.1 mm bilateral, or +0.2/−0.0 mm unilateral), "
                            "or add a drawing-level general tolerance block in the "
                            "title block that covers all untoleranced dimensions.  "
                            "Tolerances must be specified per ASME Y14.5-2018 §2.1 "
                            "and §2.7."
                        ),
                        standard_reference="ASME Y14.5-2018 §2.1, §2.7",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# FCFCompletenessRule
# ---------------------------------------------------------------------------


class FCFCompletenessRule:
    """Every ``FeatureControlFrame`` must be complete per ASME Y14.5.

    A feature control frame is considered incomplete when:

    * ``tolerance_value`` is ``None`` or ``<= 0`` — the tolerance zone is
      undefined or nonsensical.
    * The GD&T symbol requires at least one datum reference (orientation,
      location, or runout tolerances) but ``datum_references`` is empty.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 §10.1 (Feature Control Frame), §10.3 (Datum References)
    """

    rule_id: str = "FCF_COMPLETENESS_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return ``CRITICAL`` issues for each incomplete feature control frame."""
        issues: list[Issue] = []

        # Collect all FCFs: top-level + those attached to features.
        all_fcfs: list[FeatureControlFrame] = list(model.feature_control_frames)
        seen_fcf_ids: set[str] = {fcf.id for fcf in model.feature_control_frames}
        for feature in model.features:
            for fcf in feature.feature_control_frames:
                if fcf.id not in seen_fcf_ids:
                    all_fcfs.append(fcf)
                    seen_fcf_ids.add(fcf.id)

        for fcf in all_fcfs:
            # Check 1: tolerance_value must be present and positive.
            if fcf.tolerance_value is None or fcf.tolerance_value <= 0:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="MISSING_FCF_TOLERANCE_VALUE",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature control frame '{fcf.id}' "
                            f"(GD&T symbol: {fcf.gdt_symbol}) has no valid "
                            "tolerance value.  A feature control frame must "
                            "specify a positive tolerance zone value so that "
                            "the allowable geometric variation is defined."
                        ),
                        location=fcf.location,
                        corrective_action=(
                            f"Add a positive tolerance value to feature control "
                            f"frame '{fcf.id}'.  The tolerance value specifies the "
                            "diameter or width of the tolerance zone (e.g. Ø0.05 mm "
                            "for a position tolerance).  Refer to ASME Y14.5-2018 "
                            "§10.1 for the correct feature control frame format."
                        ),
                        standard_reference="ASME Y14.5-2018 §10.1",
                    )
                )

            # Check 2: symbols that require datum references must have at least one.
            symbol_upper = fcf.gdt_symbol.upper().strip()
            requires_datum = (
                fcf.gdt_symbol in _DATUM_REQUIRED_SYMBOLS
                or symbol_upper in _DATUM_REQUIRED_SYMBOLS
            )
            if requires_datum and not fcf.datum_references:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="MISSING_FCF_DATUM_REFERENCE",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature control frame '{fcf.id}' "
                            f"(GD&T symbol: {fcf.gdt_symbol}) requires at least "
                            "one datum reference per ASME Y14.5-2018 but none are "
                            "specified.  Orientation, location, and runout tolerances "
                            "must reference the Datum Reference Frame to be "
                            "meaningful."
                        ),
                        location=fcf.location,
                        corrective_action=(
                            f"Add at least one datum reference to feature control "
                            f"frame '{fcf.id}'.  For example, reference the primary "
                            "datum (e.g. 'A') that establishes the orientation or "
                            "location reference for this tolerance.  Datum references "
                            "must be defined on the drawing per ASME Y14.5-2018 "
                            "§10.3 and §4.1."
                        ),
                        standard_reference="ASME Y14.5-2018 §10.1, §10.3",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# ToleranceStackUpRule
# ---------------------------------------------------------------------------


class ToleranceStackUpRule:
    """Detect dimension chains where the tolerance stack-up exceeds the tightest tolerance.

    A tolerance stack-up occurs when multiple dimensions share features in a
    chain (each dimension's ``associated_feature_ids`` overlaps with the next).
    If the arithmetic sum of all tolerances in the chain exceeds the tightest
    (smallest total band) tolerance in that chain, the stack-up is a problem.

    The total tolerance band for a dimension is ``abs(upper) + abs(lower)``.

    Algorithm:
    1. Build a graph where nodes are feature IDs and edges are dimensions that
       connect two features (i.e. ``len(associated_feature_ids) >= 2``).
    2. Find connected components (dimension chains) in this graph.
    3. For each chain with two or more dimensions, compute:
       - ``stack_up_total``: sum of all tolerance bands in the chain.
       - ``tightest_tolerance``: minimum tolerance band in the chain.
    4. If ``stack_up_total > tightest_tolerance``, emit a ``WARNING``.

    Severity: ``WARNING``
    Standard: ASME Y14.5-2018 §2.1 (Tolerance Accumulation)
    """

    rule_id: str = "TOLERANCE_STACK_UP_RULE"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tolerance_band(tol: Tolerance) -> float:
        """Return the total tolerance band (upper deviation + |lower deviation|)."""
        return abs(tol.upper) + abs(tol.lower)

    def _build_chains(
        self, dimensions: list[Dimension]
    ) -> list[list[Dimension]]:
        """Group dimensions into chains by shared feature IDs.

        Two dimensions belong to the same chain if they share at least one
        feature ID in their ``associated_feature_ids`` lists.  We use a
        union-find approach to merge overlapping groups.
        """
        # Only consider dimensions that have at least one feature association
        # and carry a tolerance (untolerated dimensions are handled by
        # DimensionToleranceRule).
        eligible = [
            d for d in dimensions
            if d.associated_feature_ids and d.tolerance is not None
        ]

        if not eligible:
            return []

        # Union-Find
        parent: dict[int, int] = {i: i for i in range(len(eligible))}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            parent[find(x)] = find(y)

        # Map feature_id → list of dimension indices that reference it.
        feature_to_dims: dict[str, list[int]] = defaultdict(list)
        for idx, dim in enumerate(eligible):
            for fid in dim.associated_feature_ids:
                feature_to_dims[fid].append(idx)

        # Union dimensions that share a feature.
        for indices in feature_to_dims.values():
            for i in range(1, len(indices)):
                union(indices[0], indices[i])

        # Group by root.
        groups: dict[int, list[Dimension]] = defaultdict(list)
        for idx, dim in enumerate(eligible):
            groups[find(idx)].append(dim)

        return [chain for chain in groups.values() if len(chain) >= 2]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return ``WARNING`` issues for dimension chains with excessive stack-up."""
        issues: list[Issue] = []

        # Collect all tolerated dimensions with feature associations.
        all_dimensions: list[Dimension] = []
        seen_ids: set[str] = set()

        for dim in model.dimensions:
            if dim.id not in seen_ids:
                all_dimensions.append(dim)
                seen_ids.add(dim.id)

        for feature in model.features:
            for dim in feature.dimensions:
                if dim.id not in seen_ids:
                    all_dimensions.append(dim)
                    seen_ids.add(dim.id)

        chains = self._build_chains(all_dimensions)

        for chain in chains:
            # Compute per-dimension tolerance bands.
            bands = [self._tolerance_band(d.tolerance) for d in chain]  # type: ignore[arg-type]
            stack_up_total = sum(bands)
            tightest_tolerance = min(bands)

            if stack_up_total > tightest_tolerance:
                # Build a human-readable description of the chain.
                dim_ids = ", ".join(d.id for d in chain)
                band_strs = ", ".join(f"{b:.4g}" for b in bands)
                feature_ids = sorted(
                    {fid for d in chain for fid in d.associated_feature_ids}
                )
                feature_id_str = ", ".join(feature_ids)

                # Use the location of the first dimension in the chain as the
                # representative location for the issue.
                location = chain[0].location

                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="TOLERANCE_STACK_UP_VIOLATION",
                        severity=Severity.WARNING,
                        description=(
                            f"Tolerance stack-up violation detected in dimension "
                            f"chain [{dim_ids}] spanning features [{feature_id_str}].  "
                            f"Individual tolerance bands: [{band_strs}].  "
                            f"Arithmetic stack-up total: {stack_up_total:.4g}.  "
                            f"Tightest tolerance in chain: {tightest_tolerance:.4g}.  "
                            "The accumulated tolerance exceeds the tightest tolerance, "
                            "which may make it impossible to satisfy the tightest "
                            "requirement while respecting all other dimensions."
                        ),
                        location=location,
                        corrective_action=None,
                        standard_reference="ASME Y14.5-2018 §2.1",
                    )
                )

        return issues
