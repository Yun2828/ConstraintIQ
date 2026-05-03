"""Geometric constraint verification rules.

This module implements the three rules that check whether a drawing is fully
constrained with a valid datum reference frame and properly referenced GD&T
annotations:

* ``DatumReferenceFrameRule``  — a valid Datum_Reference_Frame must exist.
* ``FeatureOrientationRule``   — every Feature's orientation must be fully
                                 constrained relative to the DRF or another
                                 constrained feature.
* ``GDTDatumReferenceRule``    — every FeatureControlFrame.datum_references
                                 entry must reference a defined Datum label.

All ``CRITICAL`` issues include a non-empty ``corrective_action`` and a
``standard_reference`` pointing to the applicable ASME Y14.5-2018 clause.
"""

from __future__ import annotations

import uuid

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


def _feature_location(feature: Feature) -> LocationReference:
    """Return the feature's location, or a generic placeholder if absent."""
    if feature.location is not None:
        return feature.location
    return LocationReference(
        view_name="UNKNOWN",
        coordinates=None,
        label=feature.id,
    )


# ---------------------------------------------------------------------------
# DatumReferenceFrameRule
# ---------------------------------------------------------------------------


class DatumReferenceFrameRule:
    """Verify that a valid Datum_Reference_Frame is established on the drawing.

    A Datum Reference Frame (DRF) consists of up to three mutually perpendicular
    datum planes (primary, secondary, tertiary).  Without a primary datum the
    drawing has no reference origin and cannot be manufactured or inspected.

    * No datums at all → ``CRITICAL``
    * Only a primary datum (secondary/tertiary absent) → ``WARNING``
    * All three datums present → no issue

    Severity: ``CRITICAL`` (no datums) / ``WARNING`` (incomplete DRF)
    Standard: ASME Y14.5-2018 §4.1 (Datum Reference Frames)
    """

    rule_id: str = "DATUM_REFERENCE_FRAME_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return issues if the datum reference frame is absent or incomplete."""
        issues: list[Issue] = []

        if not model.datums:
            # No datums at all — CRITICAL
            issues.append(
                Issue(
                    issue_id=str(uuid.uuid4()),
                    rule_id=self.rule_id,
                    issue_type="MISSING_DATUM_REFERENCE_FRAME",
                    severity=Severity.CRITICAL,
                    description=(
                        "The drawing has no datum reference frame.  No datum "
                        "features are defined, so features cannot be located or "
                        "oriented relative to a reference origin.  Manufacturing "
                        "and inspection are impossible without a DRF."
                    ),
                    location=LocationReference(
                        view_name="DRAWING",
                        coordinates=None,
                        label=None,
                    ),
                    corrective_action=(
                        "Establish a Datum Reference Frame by applying datum "
                        "feature symbols (A, B, C) to three mutually perpendicular "
                        "surfaces or features.  The primary datum (A) constrains "
                        "three degrees of freedom, the secondary (B) constrains two, "
                        "and the tertiary (C) constrains one.  Apply datum feature "
                        "symbols per ASME Y14.5-2018 §4.1."
                    ),
                    standard_reference="ASME Y14.5-2018 §4.1",
                )
            )
            return issues

        # Datums exist — check whether secondary/tertiary are present.
        # We infer the DRF completeness from the number of distinct datum labels.
        # A complete DRF has at least three datums (primary, secondary, tertiary).
        # Having only one datum implies secondary and tertiary are missing.
        datum_labels = {d.label for d in model.datums}
        if len(datum_labels) < 2:
            issues.append(
                Issue(
                    issue_id=str(uuid.uuid4()),
                    rule_id=self.rule_id,
                    issue_type="INCOMPLETE_DATUM_REFERENCE_FRAME",
                    severity=Severity.WARNING,
                    description=(
                        f"The drawing defines only {len(datum_labels)} datum "
                        f"label(s) ({', '.join(sorted(datum_labels))}).  A complete "
                        "Datum Reference Frame typically requires a secondary and "
                        "tertiary datum to fully constrain part geometry for "
                        "inspection and manufacturing."
                    ),
                    location=LocationReference(
                        view_name="DRAWING",
                        coordinates=None,
                        label=None,
                    ),
                    corrective_action=(
                        "Add secondary and tertiary datum features to complete the "
                        "Datum Reference Frame.  Apply datum feature symbols to "
                        "additional surfaces or features that constrain the remaining "
                        "degrees of freedom per ASME Y14.5-2018 §4.1."
                    ),
                    standard_reference="ASME Y14.5-2018 §4.1",
                )
            )

        return issues


# ---------------------------------------------------------------------------
# FeatureOrientationRule
# ---------------------------------------------------------------------------


class FeatureOrientationRule:
    """Every Feature's orientation must be fully constrained relative to the DRF.

    A feature is considered unconstrained if it has no dimensions and no
    feature control frames.  In that state the feature has undefined degrees
    of freedom and cannot be manufactured or inspected to a known orientation.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 §4.1 (Datum Reference Frames), §6.1 (Orientation)
    """

    rule_id: str = "FEATURE_ORIENTATION_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``CRITICAL`` issue for each feature with unconstrained DOF."""
        issues: list[Issue] = []

        for feature in model.features:
            has_dimensions = bool(feature.dimensions)
            has_fcfs = bool(feature.feature_control_frames)

            if not has_dimensions and not has_fcfs:
                location = _feature_location(feature)
                issues.append(
                    Issue(
                        issue_id=str(uuid.uuid4()),
                        rule_id=self.rule_id,
                        issue_type="UNCONSTRAINED_FEATURE_ORIENTATION",
                        severity=Severity.CRITICAL,
                        description=(
                            f"Feature '{feature.id}' (type: {feature.feature_type}) "
                            "has no dimensions and no feature control frames.  Its "
                            "orientation has unconstrained degrees of freedom — the "
                            f"feature is located at {location.view_name} but its "
                            "angular orientation relative to the Datum Reference Frame "
                            "is undefined."
                        ),
                        location=location,
                        corrective_action=(
                            f"Add dimensions or GD&T feature control frames to "
                            f"feature '{feature.id}' that fully constrain its "
                            "orientation relative to the Datum Reference Frame.  "
                            "For example, apply an orientation tolerance (parallelism, "
                            "perpendicularity, or angularity) referencing the "
                            "established datums, or add linear/angular dimensions "
                            "that locate and orient the feature per ASME Y14.5-2018 "
                            "§4.1 and §6.1."
                        ),
                        standard_reference="ASME Y14.5-2018 §4.1, §6.1",
                    )
                )

        return issues


# ---------------------------------------------------------------------------
# GDTDatumReferenceRule
# ---------------------------------------------------------------------------


class GDTDatumReferenceRule:
    """Every FeatureControlFrame.datum_references entry must reference a defined Datum.

    A feature control frame that references a datum label not present in the
    model's datum list is invalid — the GD&T callout cannot be interpreted
    during inspection.

    Severity: ``CRITICAL``
    Standard: ASME Y14.5-2018 §4.1 (Datum Reference Frames), §10.1 (FCF)
    """

    rule_id: str = "GDT_DATUM_REFERENCE_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        """Return one ``CRITICAL`` issue for each FCF referencing an undefined datum."""
        issues: list[Issue] = []

        # Build the set of defined datum labels from the model.
        defined_datum_labels: set[str] = {d.label for d in model.datums}

        # Check top-level feature control frames.
        all_fcfs = list(model.feature_control_frames)

        # Also check FCFs attached directly to features.
        for feature in model.features:
            for fcf in feature.feature_control_frames:
                if fcf not in all_fcfs:
                    all_fcfs.append(fcf)

        for fcf in all_fcfs:
            for datum_ref in fcf.datum_references:
                if datum_ref not in defined_datum_labels:
                    issues.append(
                        Issue(
                            issue_id=str(uuid.uuid4()),
                            rule_id=self.rule_id,
                            issue_type="UNDEFINED_DATUM_REFERENCE",
                            severity=Severity.CRITICAL,
                            description=(
                                f"Feature control frame '{fcf.id}' "
                                f"(GD&T symbol: {fcf.gdt_symbol}) references "
                                f"datum '{datum_ref}', which is not defined in "
                                "the drawing.  The GD&T callout cannot be "
                                "interpreted during inspection without a "
                                "corresponding datum feature symbol."
                            ),
                            location=fcf.location,
                            corrective_action=(
                                f"Either define datum '{datum_ref}' by applying a "
                                "datum feature symbol to an appropriate surface or "
                                "feature, or correct the datum reference in feature "
                                f"control frame '{fcf.id}' to reference an existing "
                                "defined datum.  All datum references in feature "
                                "control frames must correspond to datum feature "
                                "symbols on the drawing per ASME Y14.5-2018 §4.1 "
                                "and §10.1."
                            ),
                            standard_reference="ASME Y14.5-2018 §4.1, §10.1",
                        )
                    )

        return issues
