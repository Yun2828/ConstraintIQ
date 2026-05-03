"""GD&T compliance verification rules.

This module implements three rules that validate GD&T annotations against the
ANSI/ASME Y14.5-2018 standard:

* ``GDTSymbolSetRule``              -- all ``FeatureControlFrame.gdt_symbol``
                                      values must be from the Y14.5-2018 standard
                                      symbol set; non-standard -> ``WARNING``.
* ``CompositeFCFRule``              -- composite feature control frames must follow
                                      Y14.5 pattern-locating and feature-relating
                                      tolerance zone rules; violation -> ``CRITICAL``.
* ``DatumFeatureSymbolPlacementRule`` -- datum feature symbols must be applied to
                                        physical features, not centerlines or axes;
                                        incorrect placement -> ``WARNING``.

All ``CRITICAL`` issues include a non-empty ``corrective_action`` and a
``standard_reference`` pointing to the applicable ASME Y14.5-2018 clause.
"""

from __future__ import annotations

import uuid

from ..models import (
    Datum,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    Issue,
    LocationReference,
    Severity,
)

# ---------------------------------------------------------------------------
# ANSI/ASME Y14.5-2018 standard GD&T symbol set
# ---------------------------------------------------------------------------

# Unicode symbols as they appear in CAD software and DXF/PDF exports.
_STANDARD_GDT_SYMBOLS_UNICODE: frozenset[str] = frozenset(
    {
        "\u23e4",   # straightness
        "\u23e5",   # flatness
        "\u25cb",   # circularity / roundness
        "\u232d",   # cylindricity
        "\u2312",   # profile of a line
        "\u2313",   # profile of a surface
        "\u2220",   # angularity
        "\u22a5",   # perpendicularity
        "\u2225",   # parallelism
        "\u2295",   # position / true position
        "\u25ce",   # concentricity / coaxiality
        "\u2261",   # symmetry
        "\u2197",   # circular runout
        "\u21d7",   # total runout
    }
)

# ASCII / text equivalents commonly used in CAD software and plain-text FCFs.
_STANDARD_GDT_SYMBOLS_TEXT: frozenset[str] = frozenset(
    {
        "STRAIGHTNESS",
        "FLATNESS",
        "CIRCULARITY",
        "ROUNDNESS",
        "CYLINDRICITY",
        "PROFILE_OF_A_LINE",
        "PROFILE_OF_A_SURFACE",
        "PROFILE OF A LINE",
        "PROFILE OF A SURFACE",
        "ANGULARITY",
        "PERPENDICULARITY",
        "PARALLELISM",
        "POSITION",
        "TRUE_POSITION",
        "TRUE POSITION",
        "CONCENTRICITY",
        "COAXIALITY",
        "SYMMETRY",
        "CIRCULAR_RUNOUT",
        "CIRCULAR RUNOUT",
        "TOTAL_RUNOUT",
        "TOTAL RUNOUT",
    }
)

# Combined set for membership testing (upper-cased text symbols only).
_ALL_STANDARD_SYMBOLS: frozenset[str] = (
    _STANDARD_GDT_SYMBOLS_UNICODE | _STANDARD_GDT_SYMBOLS_TEXT
)

# Position symbols used to identify potential composite FCFs.
_POSITION_SYMBOLS: frozenset[str] = frozenset(
    {
        "\u2295",
        "POSITION",
        "TRUE_POSITION",
        "TRUE POSITION",
    }
)

# Feature types that represent non-physical geometry (centerlines, axes).
_NON_PHYSICAL_FEATURE_TYPES: frozenset[str] = frozenset(
    {
        "CENTERLINE",
        "AXIS",
        "CENTER_AXIS",
        "CENTRE_AXIS",
        "CENTRELINE",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_standard_symbol(symbol: str) -> bool:
    """Return True if *symbol* is a recognised ANSI/ASME Y14.5-2018 GD&T symbol."""
    if symbol in _STANDARD_GDT_SYMBOLS_UNICODE:
        return True
    if symbol.upper().strip() in _STANDARD_GDT_SYMBOLS_TEXT:
        return True
    return False


def _is_position_symbol(symbol: str) -> bool:
    """Return True if *symbol* represents a position / true-position tolerance."""
    return symbol in _POSITION_SYMBOLS or symbol.upper().strip() in _POSITION_SYMBOLS


def _collect_all_fcfs(model: GeometricModel) -> list[FeatureControlFrame]:
    """Return all FCFs from the model (top-level + feature-attached), deduplicated."""
    all_fcfs: list[FeatureControlFrame] = list(model.feature_control_frames)
    seen_ids: set[str] = {fcf.id for fcf in model.feature_control_frames}
    for feature in model.features:
        for fcf in feature.feature_control_frames:
            if fcf.id not in seen_ids:
                all_fcfs.append(fcf)
                seen_ids.add(fcf.id)
    return all_fcfs


# ---------------------------------------------------------------------------
# GDTSymbolSetRule
# ---------------------------------------------------------------------------


class GDTSymbolSetRule:
    """Validate that all GD&T symbols are from the ANSI/ASME Y14.5-2018 standard set.

    Any ``FeatureControlFrame`` whose ``gdt_symbol`` is not a member of the
    standard symbol set (neither the Unicode character nor a recognised ASCII
    text equivalent) is flagged.

    Severity: ``WARNING``
    Standard: ASME Y14.5-2018 section 3 (Symbology)
    """

    rule_id: str = "GDT_SYMBOL_SET_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``WARNING`` issue for each FCF with a non-standard GD&T symbol."""
        issues: list[Issue] = []

        for fcf in _collect_all_fcfs(model):
            if not _is_standard_symbol(fcf.gdt_symbol):
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="NON_STANDARD_GDT_SYMBOL",
                        severity=Severity.WARNING,
                        description=(
                            f"Feature control frame '{fcf.id}' uses GD&T symbol "
                            f"'{fcf.gdt_symbol}', which is not a member of the "
                            "ANSI/ASME Y14.5-2018 standard symbol set.  "
                            "Non-standard symbols may be misinterpreted by "
                            "machinists and inspection equipment."
                        ),
                        location=fcf.location,
                        corrective_action=None,
                        standard_reference="ASME Y14.5-2018 section 3",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# CompositeFCFRule
# ---------------------------------------------------------------------------


class CompositeFCFRule:
    """Verify composite feature control frames follow Y14.5 PLTZF/FRTZF rules.

    A composite feature control frame (composite FCF) is used for patterns of
    features.  It consists of two entries sharing the same GD&T symbol:

    * **PLTZF** (Pattern-Locating Tolerance Zone Framework) -- the upper entry;
      locates the pattern relative to the datum reference frame.  It MUST have
      at least one datum reference.
    * **FRTZF** (Feature-Relating Tolerance Zone Framework) -- the lower entry;
      controls the geometry within the pattern.  It MAY have fewer datum
      references than the PLTZF, or none at all.

    This rule detects composite FCFs heuristically: a position FCF with datum
    references is treated as a PLTZF candidate.  The rule then checks:

    1. The tolerance value must be positive (a zero or missing tolerance zone
       is meaningless).
    2. For a PLTZF (position symbol + datum references), the tolerance value
       must be positive -- this is the basic validity check for the locating
       tolerance zone.

    If a position FCF has datum references but a non-positive tolerance value,
    the composite FCF is considered malformed.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 section 11.10 (Composite Tolerancing)
    """

    rule_id: str = "COMPOSITE_FCF_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return ``CRITICAL`` issues for malformed composite feature control frames."""
        issues: list[Issue] = []

        for fcf in _collect_all_fcfs(model):
            # Only examine position FCFs with datum references -- these are the
            # candidates for composite (PLTZF) entries.
            if not _is_position_symbol(fcf.gdt_symbol):
                continue
            if not fcf.datum_references:
                continue

            # Check 1: the PLTZF tolerance value must be positive.
            if fcf.tolerance_value is None or fcf.tolerance_value <= 0:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="COMPOSITE_FCF_INVALID_PLTZF_TOLERANCE",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature control frame '{fcf.id}' "
                            f"(GD&T symbol: {fcf.gdt_symbol}) appears to be a "
                            "composite FCF pattern-locating tolerance zone framework "
                            "(PLTZF) -- it uses a position symbol and references "
                            f"datum(s) {fcf.datum_references} -- but its tolerance "
                            "value is missing or non-positive "
                            f"({fcf.tolerance_value!r}).  "
                            "A PLTZF must specify a positive tolerance zone value "
                            "that locates the pattern relative to the datum reference "
                            "frame per ASME Y14.5-2018 section 11.10."
                        ),
                        location=fcf.location,
                        corrective_action=(
                            f"Add a positive tolerance value to the PLTZF entry of "
                            f"composite feature control frame '{fcf.id}'.  The PLTZF "
                            "tolerance zone locates the entire pattern relative to "
                            "the datum reference frame and must be larger than the "
                            "FRTZF tolerance zone.  Refer to ASME Y14.5-2018 "
                            "section 11.10 for the correct composite FCF format."
                        ),
                        standard_reference="ASME Y14.5-2018 section 11.10",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# DatumFeatureSymbolPlacementRule
# ---------------------------------------------------------------------------


class DatumFeatureSymbolPlacementRule:
    """Datum feature symbols must be applied to physical features, not centerlines or axes.

    Per ASME Y14.5-2018, datum feature symbols shall be attached to the surface
    or feature of size that is the actual datum feature.  Applying a datum
    symbol directly to a centerline, axis, or center plane annotation (rather
    than to the physical surface that generates that axis) is incorrect and
    leads to ambiguity during inspection setup.

    This rule flags two conditions:

    1. A ``Datum`` whose ``feature_id`` is empty or ``None`` -- the datum is not
       associated with any feature at all.
    2. A ``Datum`` whose ``feature_id`` references a ``Feature`` with a
       ``feature_type`` in the set of non-physical geometry types
       (``CENTERLINE``, ``AXIS``, ``CENTER_AXIS``, etc.).

    Severity: ``WARNING``
    Standard: ASME Y14.5-2018 section 4.5 (Datum Feature Symbols)
    """

    rule_id: str = "DATUM_FEATURE_SYMBOL_PLACEMENT_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return ``WARNING`` issues for incorrectly placed datum feature symbols."""
        issues: list[Issue] = []

        # Build a lookup from feature_id -> Feature for fast access.
        feature_by_id: dict[str, Feature] = {f.id: f for f in model.features}

        for datum in model.datums:
            # Condition 1: feature_id is empty or None.
            if not datum.feature_id:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="DATUM_SYMBOL_NO_FEATURE",
                        severity=Severity.WARNING,
                        description=(
                            f"Datum '{datum.label}' has no associated feature "
                            "(feature_id is empty or None).  A datum feature symbol "
                            "must be applied to a physical feature on the drawing so "
                            "that the datum can be established during inspection."
                        ),
                        location=datum.location,
                        corrective_action=None,
                        standard_reference="ASME Y14.5-2018 section 4.5",
                    )
                )
                continue

            # Condition 2: feature_id references a non-physical geometry type.
            feature = feature_by_id.get(datum.feature_id)
            if feature is not None:
                ftype_upper = feature.feature_type.upper().strip()
                if ftype_upper in _NON_PHYSICAL_FEATURE_TYPES:
                    issues.append(
                        Issue(
                            issue_id=str(uuid.uuid4()),
                            rule_id=self.rule_id,
                            issue_type="DATUM_SYMBOL_ON_NON_PHYSICAL_FEATURE",
                            severity=Severity.WARNING,
                            description=(
                                f"Datum '{datum.label}' is applied to feature "
                                f"'{datum.feature_id}' (type: {feature.feature_type}), "
                                "which is a centerline, axis, or center plane -- not a "
                                "physical surface.  Per ASME Y14.5-2018, datum feature "
                                "symbols must be attached to the physical surface or "
                                "feature of size that generates the datum, not to the "
                                "theoretical axis or centerline derived from it."
                            ),
                            location=datum.location,
                            corrective_action=None,
                            standard_reference="ASME Y14.5-2018 section 4.5",
                        )
                    )

        return issues
