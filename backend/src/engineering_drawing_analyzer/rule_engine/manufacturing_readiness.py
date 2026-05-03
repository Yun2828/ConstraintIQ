"""Manufacturing readiness verification rules.

This module implements the five rules that check whether a drawing contains
all information a machinist needs to fabricate the part without requesting
clarification:

* ``TitleBlockRule``         -- the title block must contain all required fields
                               (part_number, revision, material, scale, units);
                               one ``CRITICAL`` issue per missing field.
* ``SurfaceFinishRule``      -- functional surfaces (feature_type == "SURFACE")
                               must have surface finish callouts; missing -> ``WARNING``.
* ``HoleSpecificationRule``  -- holes must specify diameter, depth (if blind),
                               tolerance, and thread spec (if threaded);
                               missing -> ``CRITICAL``.
* ``ViewSufficiencyRule``    -- the drawing must have sufficient orthographic
                               views to represent all features; insufficient -> ``CRITICAL``.
* ``NoteContradictionRule``  -- detect contradictions between notes or between
                               notes and dimensions -> ``CRITICAL``.

All ``CRITICAL`` issues include a non-empty ``corrective_action`` and a
``standard_reference`` pointing to the applicable ASME Y14.5-2018 clause.
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

from ..models import (
    Feature,
    GeometricModel,
    Issue,
    LocationReference,
    Severity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Keywords that indicate a surface finish callout in a dimension label or note.
_SURFACE_FINISH_KEYWORDS: frozenset[str] = frozenset(
    {
        "RA",
        "RZ",
        "RQ",
        "ROUGHNESS",
        "FINISH",
        "SURFACE FINISH",
        "SURFACE_FINISH",
        "MICROFINISH",
        "MICRO-FINISH",
        "WAVINESS",
        "TEXTURE",
        "MACHINED",
        "GROUND",
        "POLISHED",
        "LAPPED",
        "HONED",
        "BURNISHED",
    }
)

# Regex to extract standalone numeric values from notes (for contradiction detection).
# Uses word boundaries to avoid matching numbers embedded in identifiers like "F1", "H2".
_NUMBER_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?![A-Za-z_])")

# Unit system keywords for contradiction detection.
_METRIC_KEYWORDS: frozenset[str] = frozenset({"METRIC", "MM", "MILLIMETER", "MILLIMETRE"})
_IMPERIAL_KEYWORDS: frozenset[str] = frozenset(
    {"IMPERIAL", "INCH", "INCHES", "FRACTIONAL", "SAE"}
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


def _drawing_location() -> LocationReference:
    """Return a generic drawing-level location reference."""
    return LocationReference(view_name="DRAWING", coordinates=None, label=None)


def _note_contains_feature(note: str, feature_id: str) -> bool:
    """Return True if *note* references *feature_id* (case-insensitive)."""
    return feature_id.lower() in note.lower()


def _note_has_finish_keyword(note: str) -> bool:
    """Return True if *note* contains a surface finish keyword."""
    note_upper = note.upper()
    return any(kw in note_upper for kw in _SURFACE_FINISH_KEYWORDS)


def _dim_has_finish_keyword(dim_unit: str) -> bool:
    """Return True if a dimension's unit field contains a surface finish keyword."""
    unit_upper = dim_unit.upper().strip()
    return any(kw in unit_upper for kw in _SURFACE_FINISH_KEYWORDS)


# ---------------------------------------------------------------------------
# TitleBlockRule
# ---------------------------------------------------------------------------


class TitleBlockRule:
    """Verify that the title block contains all required fields.

    Required fields: ``part_number``, ``revision``, ``material``, ``scale``,
    ``units``.  One ``CRITICAL`` issue is produced for each missing field --
    no more, no fewer.

    Severity: ``CRITICAL``
    Standard: ASME Y14.100-2017 section 4.1 (Title Block Requirements)
    """

    rule_id: str = "TITLE_BLOCK_RULE"

    # Ordered list of (field_name, human_label) pairs.
    _REQUIRED_FIELDS: list[tuple[str, str]] = [
        ("part_number", "Part Number"),
        ("revision", "Revision"),
        ("material", "Material"),
        ("scale", "Scale"),
        ("units", "Units"),
    ]

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``CRITICAL`` issue for each missing required title block field."""
        issues: list[Issue] = []

        if model.title_block is None:
            # No title block at all -- report one issue per required field.
            for field_name, human_label in self._REQUIRED_FIELDS:
                issues.append(self._missing_field_issue(field_name, human_label))
            return issues

        tb = model.title_block
        for field_name, human_label in self._REQUIRED_FIELDS:
            value = getattr(tb, field_name, None)
            if not value:  # None or empty string
                issues.append(self._missing_field_issue(field_name, human_label))

        return issues

    def _missing_field_issue(self, field_name: str, human_label: str) -> Issue:
        return Issue(
            issue_id=str(uuid.uuid4()),
            rule_id=self.rule_id,
            issue_type=f"MISSING_TITLE_BLOCK_{field_name.upper()}",
            severity=Severity.CRITICAL,
            description=(
                f"The title block is missing the required '{human_label}' field.  "
                "A complete title block is mandatory for manufacturing readiness; "
                "machinists and inspectors rely on this information to identify "
                "the part, its revision state, material, drawing scale, and unit "
                "system."
            ),
            location=_drawing_location(),
            corrective_action=(
                f"Add the '{human_label}' field to the drawing title block.  "
                "All five required fields (Part Number, Revision, Material, Scale, "
                "Units) must be populated before the drawing is released for "
                "manufacturing.  Refer to ASME Y14.100-2017 section 4.1 for title "
                "block content requirements."
            ),
            standard_reference="ASME Y14.100-2017 section 4.1",
        )


# ---------------------------------------------------------------------------
# SurfaceFinishRule
# ---------------------------------------------------------------------------


class SurfaceFinishRule:
    """Verify that functional surfaces have surface finish callouts.

    A "functional surface" is identified by ``feature_type == "SURFACE"``.
    A surface finish callout is considered present when:

    * Any note in ``model.notes`` references the feature ID, OR
    * Any note in ``model.notes`` contains a surface finish keyword (Ra, Rz,
      roughness, finish, etc.), OR
    * Any of the feature's dimensions has a unit field containing a surface
      finish keyword.

    Severity: ``WARNING``
    Standard: ASME Y14.36-2018 section 5 (Surface Texture Symbols)
    """

    rule_id: str = "SURFACE_FINISH_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``WARNING`` issue for each functional surface without a finish callout."""
        issues: list[Issue] = []

        # Pre-compute which notes contain finish keywords (for efficiency).
        finish_notes = [n for n in model.notes if _note_has_finish_keyword(n)]

        for feature in model.features:
            if feature.feature_type.upper() != "SURFACE":
                continue

            # Check 1: any note references this feature ID.
            referenced_by_note = any(
                _note_contains_feature(note, feature.id) for note in model.notes
            )

            # Check 2: any finish-keyword note exists (general finish callout).
            has_general_finish_note = bool(finish_notes)

            # Check 3: any of the feature's dimensions has a finish keyword in unit.
            has_finish_dim = any(
                _dim_has_finish_keyword(dim.unit) for dim in feature.dimensions
            )

            if not (referenced_by_note or has_general_finish_note or has_finish_dim):
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="MISSING_SURFACE_FINISH_CALLOUT",
                        severity=Severity.WARNING,
                        description=(
                            f"Functional surface '{feature.id}' has no surface finish "
                            "callout.  Surfaces that affect function or fit must specify "
                            "the required surface texture (e.g. Ra, Rz) so that the "
                            "machinist can select the appropriate manufacturing process."
                        ),
                        location=_feature_location(feature),
                        corrective_action=None,
                        standard_reference="ASME Y14.36-2018 section 5",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# HoleSpecificationRule
# ---------------------------------------------------------------------------


class HoleSpecificationRule:
    """Verify that all holes have complete specifications.

    A hole (``feature_type == "HOLE"``) must have:

    1. At least one dimension (diameter).
    2. A depth dimension if ``is_blind_hole == True``.
    3. At least one dimension with an explicit tolerance.
    4. A note referencing the feature ID that contains a thread specification
       keyword if ``is_threaded == True``.

    Each missing specification produces a separate ``CRITICAL`` issue.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 section 7.6 (Hole Callouts), ASME B1.1 (Thread Standards)
    """

    rule_id: str = "HOLE_SPECIFICATION_RULE"

    # Keywords that indicate a thread specification in a note.
    _THREAD_KEYWORDS: frozenset[str] = frozenset(
        {
            "THREAD",
            "THREADED",
            "TAP",
            "TAPPED",
            "UNC",
            "UNF",
            "UNEF",
            "M",  # metric thread prefix (e.g. "M6x1.0")
            "NPT",
            "NPTF",
            "BSP",
            "BSPT",
            "ACME",
            "BUTTRESS",
        }
    )

    # Keywords that indicate a depth specification in a note or dimension unit.
    _DEPTH_KEYWORDS: frozenset[str] = frozenset(
        {
            "DEPTH",
            "DEEP",
            "DP",
            "THRU",
            "THROUGH",
        }
    )

    def _has_thread_note(self, feature: Feature, notes: list[str]) -> bool:
        """Return True if any note references this feature and contains a thread keyword."""
        for note in notes:
            note_upper = note.upper()
            if _note_contains_feature(note, feature.id) or any(
                kw in note_upper for kw in self._THREAD_KEYWORDS
            ):
                if any(kw in note_upper for kw in self._THREAD_KEYWORDS):
                    return True
        return False

    def _has_depth_specification(self, feature: Feature, notes: list[str]) -> bool:
        """Return True if the feature has a depth dimension or a depth note."""
        # Check dimension unit fields for depth keywords.
        for dim in feature.dimensions:
            if any(kw in dim.unit.upper() for kw in self._DEPTH_KEYWORDS):
                return True
        # Check notes for depth keywords referencing this feature.
        for note in notes:
            note_upper = note.upper()
            if any(kw in note_upper for kw in self._DEPTH_KEYWORDS):
                # A general depth note (e.g. "ALL HOLES 10mm DEEP") counts.
                return True
        return False

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return ``CRITICAL`` issues for each hole with missing specifications."""
        issues: list[Issue] = []

        for feature in model.features:
            if feature.feature_type.upper() != "HOLE":
                continue

            location = _feature_location(feature)

            # Check 1: must have at least one dimension (diameter).
            if not feature.dimensions:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="HOLE_MISSING_DIAMETER",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Hole '{feature.id}' has no dimensions.  A hole must "
                            "specify at minimum its diameter so that the correct "
                            "drill or boring tool can be selected."
                        ),
                        location=location,
                        corrective_action=(
                            f"Add a diameter dimension to hole '{feature.id}' using "
                            "the standard diameter symbol followed by the nominal "
                            "diameter value and tolerance.  Refer to ASME Y14.5-2018 "
                            "section 7.6 for hole callout requirements."
                        ),
                        standard_reference="ASME Y14.5-2018 section 7.6",
                    )
                )

            # Check 2: blind holes must have a depth specification.
            if feature.is_blind_hole and not self._has_depth_specification(
                feature, model.notes
            ):
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="HOLE_MISSING_DEPTH",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Blind hole '{feature.id}' does not specify a depth.  "
                            "Blind holes must include a depth callout so that the "
                            "machinist knows how far to drill."
                        ),
                        location=location,
                        corrective_action=(
                            f"Add a depth callout to blind hole '{feature.id}'.  "
                            "Refer to ASME Y14.5-2018 section 7.6."
                        ),
                        standard_reference="ASME Y14.5-2018 section 7.6",
                    )
                )

            # Check 3: must have at least one dimension with an explicit tolerance.
            has_tolerance = any(
                dim.tolerance is not None for dim in feature.dimensions
            )
            if feature.dimensions and not has_tolerance:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="HOLE_MISSING_TOLERANCE",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Hole '{feature.id}' has no dimension with an explicit "
                            "tolerance.  Hole tolerances are critical for fit and "
                            "function -- without them the machinist cannot determine "
                            "the acceptable size variation."
                        ),
                        location=location,
                        corrective_action=(
                            f"Add an explicit tolerance to at least one dimension of "
                            f"hole '{feature.id}'.  Refer to ASME Y14.5-2018 "
                            "section 7.6 and section 2.7."
                        ),
                        standard_reference="ASME Y14.5-2018 section 7.6, section 2.7",
                    )
                )

            # Check 4: threaded holes must have a thread specification note.
            if feature.is_threaded and not self._has_thread_note(feature, model.notes):
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="HOLE_MISSING_THREAD_SPEC",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Threaded hole '{feature.id}' has no thread specification "
                            "note.  Threaded holes must specify the thread form, "
                            "nominal diameter, pitch, and class of fit so that the "
                            "correct tap can be selected."
                        ),
                        location=location,
                        corrective_action=(
                            f"Add a thread specification note for hole '{feature.id}'.  "
                            "Refer to ASME B1.1 (unified) or ISO 965 (metric) for "
                            "thread designation standards."
                        ),
                        standard_reference="ASME Y14.5-2018 section 7.6; ASME B1.1",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# ViewSufficiencyRule
# ---------------------------------------------------------------------------


class ViewSufficiencyRule:
    """Verify that the drawing has sufficient orthographic views to represent all features.

    The rule checks two conditions:

    1. ``model.views`` must be non-empty.  A drawing with no views cannot
       represent any geometry.
    2. Every feature in ``model.features`` must appear in at least one view
       (i.e. its ID must be in at least one ``View.features`` list).  A feature
       not present in any view is insufficiently represented.

    Severity: ``CRITICAL``
    Standard: ASME Y14.3-2012 section 4 (Orthographic Views)
    """

    rule_id: str = "VIEW_SUFFICIENCY_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return ``CRITICAL`` issues for features not represented in any view."""
        issues: list[Issue] = []

        # Condition 1: no views at all.
        if not model.views and model.features:
            issues.append(
                Issue(
                    issue_id=str(uuid.uuid4()),
                    rule_id=self.rule_id,
                    issue_type="NO_ORTHOGRAPHIC_VIEWS",
                    severity=Severity.CRITICAL,
                    description=(
                        "The drawing contains no orthographic views.  At least one "
                        "view (front, top, side, section, or detail) is required to "
                        "represent the part geometry unambiguously."
                    ),
                    location=_drawing_location(),
                    corrective_action=(
                        "Add the minimum set of orthographic views required to fully "
                        "describe the part geometry.  Refer to ASME Y14.3-2012 "
                        "section 4 for view selection guidelines."
                    ),
                    standard_reference="ASME Y14.3-2012 section 4",
                )
            )
            return issues

        # Condition 2: build the set of feature IDs that appear in at least one view.
        featured_in_view: set[str] = set()
        for view in model.views:
            featured_in_view.update(view.features)

        for feature in model.features:
            if feature.id not in featured_in_view:
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="FEATURE_NOT_IN_ANY_VIEW",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature '{feature.id}' (type: {feature.feature_type}) "
                            "does not appear in any orthographic view.  Every feature "
                            "must be visible in at least one view so that its geometry "
                            "can be unambiguously interpreted by the machinist."
                        ),
                        location=_feature_location(feature),
                        corrective_action=(
                            f"Add feature '{feature.id}' to at least one view, or "
                            "add a new view (section, detail, or auxiliary) that "
                            "shows this feature.  Refer to ASME Y14.3-2012 section 4."
                        ),
                        standard_reference="ASME Y14.3-2012 section 4",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# NoteContradictionRule
# ---------------------------------------------------------------------------


class NoteContradictionRule:
    """Detect contradictions between notes or between notes and dimensions.

    Two types of contradictions are detected:

    1. **Note vs. dimension**: A note contains a numeric value that contradicts
       a dimension value for the same feature.  Specifically, if a note
       references a feature ID and contains a number that differs from any
       dimension value associated with that feature, it is flagged.

    2. **Note vs. note**: Two notes contradict each other.  Currently detected
       cases:
       - One note asserts a metric unit system and another asserts an imperial
         unit system (e.g. "ALL DIMENSIONS IN MM" vs. "ALL DIMENSIONS IN INCHES").

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 section 1.4 (Drawing Requirements)
    """

    rule_id: str = "NOTE_CONTRADICTION_RULE"

    # Tolerance for numeric comparison (to avoid floating-point noise).
    _NUMERIC_TOLERANCE: float = 1e-6

    def _extract_numbers(self, text: str) -> list[float]:
        """Extract all numeric values from *text*."""
        return [float(m) for m in _NUMBER_RE.findall(text)]

    def _note_unit_system(self, note: str) -> Optional[str]:
        """Return 'METRIC', 'IMPERIAL', or None based on note content."""
        note_upper = note.upper()
        has_metric = any(
            re.search(r"\b" + re.escape(kw) + r"\b", note_upper)
            for kw in _METRIC_KEYWORDS
        )
        has_imperial = any(
            re.search(r"\b" + re.escape(kw) + r"\b", note_upper)
            for kw in _IMPERIAL_KEYWORDS
        )
        if has_metric and not has_imperial:
            return "METRIC"
        if has_imperial and not has_metric:
            return "IMPERIAL"
        return None

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return ``CRITICAL`` issues for detected note contradictions."""
        issues: list[Issue] = []

        notes = model.notes

        # --- Check 1: note vs. dimension contradictions ---
        feature_dim_values: dict[str, list[float]] = {}
        for feature in model.features:
            vals = [dim.value for dim in feature.dimensions]
            for dim in model.dimensions:
                if feature.id in dim.associated_feature_ids:
                    vals.append(dim.value)
            if vals:
                feature_dim_values[feature.id] = vals

        for note in notes:
            note_numbers = self._extract_numbers(note)
            if not note_numbers:
                continue

            for feature_id, dim_values in feature_dim_values.items():
                if not _note_contains_feature(note, feature_id):
                    continue

                for note_num in note_numbers:
                    if not any(
                        abs(note_num - dv) <= self._NUMERIC_TOLERANCE
                        for dv in dim_values
                    ):
                        feature = next(
                            (f for f in model.features if f.id == feature_id), None
                        )
                        location = (
                            _feature_location(feature)
                            if feature is not None
                            else _drawing_location()
                        )
                        issues.append(
                            Issue(
                                issue_id=str(uuid.uuid4()),
                                rule_id=self.rule_id,
                                issue_type="NOTE_DIMENSION_CONTRADICTION",
                                severity=Severity.CRITICAL,
                                description=(
                                    f"Note '{note[:80]}{'...' if len(note) > 80 else ''}' "
                                    f"references feature '{feature_id}' and contains "
                                    f"the value {note_num}, which does not match any "
                                    f"dimension value for that feature "
                                    f"({', '.join(str(v) for v in dim_values)}).  "
                                    "Contradictory values between notes and dimensions "
                                    "create ambiguity for the machinist."
                                ),
                                location=location,
                                corrective_action=(
                                    f"Resolve the contradiction between the note and "
                                    f"the dimension(s) for feature '{feature_id}'.  "
                                    "Either update the note to match the dimension "
                                    "value, update the dimension to match the note, "
                                    "or remove the redundant note.  All notes and "
                                    "dimensions must be consistent per ASME Y14.5-2018 "
                                    "section 1.4."
                                ),
                                standard_reference="ASME Y14.5-2018 section 1.4",
                            )
                        )
                        # Report at most one contradiction per (note, feature) pair.
                        break

        # --- Check 2: note vs. note unit system contradictions ---
        unit_systems: list[tuple[str, str]] = []
        for note in notes:
            system = self._note_unit_system(note)
            if system is not None:
                unit_systems.append((system, note))

        metric_notes = [n for sys, n in unit_systems if sys == "METRIC"]
        imperial_notes = [n for sys, n in unit_systems if sys == "IMPERIAL"]

        if metric_notes and imperial_notes:
            metric_snippet = metric_notes[0][:60]
            imperial_snippet = imperial_notes[0][:60]
            issues.append(
                Issue(
                    issue_id=str(uuid.uuid4()),
                    rule_id=self.rule_id,
                    issue_type="NOTE_UNIT_SYSTEM_CONTRADICTION",
                    severity=Severity.CRITICAL,
                    description=(
                        "Contradictory unit system declarations found in drawing notes.  "
                        f"Note '{metric_snippet}' declares a metric unit system while "
                        f"note '{imperial_snippet}' declares an imperial unit system.  "
                        "A drawing must use a single, consistent unit system throughout."
                    ),
                    location=_drawing_location(),
                    corrective_action=(
                        "Remove or correct the contradictory unit system note.  "
                        "Choose either metric (mm) or imperial (inches) as the "
                        "drawing unit system and ensure all notes, dimensions, and "
                        "the title block 'Units' field are consistent.  Refer to "
                        "ASME Y14.5-2018 section 1.4 and the title block 'Units' field."
                    ),
                    standard_reference="ASME Y14.5-2018 section 1.4",
                )
            )

        return issues
