"""Rule Engine subpackage for the Engineering Drawing Analyzer.

This package contains the `VerificationRule` protocol, the `RuleEngine` class,
all rule modules organized by verification domain, and factory / report-building
helpers.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from ..models import Issue, Severity, VerificationReport
from .engine import RuleEngine, VerificationRule

# --- dimension_completeness ---
from .dimension_completeness import (
    AngularDimensionRule,
    OverDimensionRule,
    PositionDimensionRule,
    SizeDimensionRule,
)

# --- geometric_constraints ---
from .geometric_constraints import (
    DatumReferenceFrameRule,
    FeatureOrientationRule,
    GDTDatumReferenceRule,
)

# --- tolerance_verification ---
from .tolerance_verification import (
    DimensionToleranceRule,
    FCFCompletenessRule,
    ToleranceStackUpRule,
)

# --- gdt_compliance ---
from .gdt_compliance import (
    CompositeFCFRule,
    DatumFeatureSymbolPlacementRule,
    GDTSymbolSetRule,
)

# --- manufacturing_readiness ---
from .manufacturing_readiness import (
    HoleSpecificationRule,
    NoteContradictionRule,
    SurfaceFinishRule,
    TitleBlockRule,
    ViewSufficiencyRule,
)

__all__ = [
    # Engine framework
    "RuleEngine",
    "VerificationRule",
    # dimension_completeness
    "SizeDimensionRule",
    "PositionDimensionRule",
    "OverDimensionRule",
    "AngularDimensionRule",
    # geometric_constraints
    "DatumReferenceFrameRule",
    "FeatureOrientationRule",
    "GDTDatumReferenceRule",
    # tolerance_verification
    "DimensionToleranceRule",
    "FCFCompletenessRule",
    "ToleranceStackUpRule",
    # gdt_compliance
    "GDTSymbolSetRule",
    "CompositeFCFRule",
    "DatumFeatureSymbolPlacementRule",
    # manufacturing_readiness
    "TitleBlockRule",
    "SurfaceFinishRule",
    "HoleSpecificationRule",
    "ViewSufficiencyRule",
    "NoteContradictionRule",
    # Factory and report helpers
    "create_default_engine",
    "build_verification_report",
]


# ---------------------------------------------------------------------------
# Systemic pattern detection threshold
# ---------------------------------------------------------------------------
_SYSTEMIC_PATTERN_THRESHOLD = 3


def create_default_engine() -> RuleEngine:
    """Create a ``RuleEngine`` pre-loaded with all rule modules in the correct order.

    Registration order:
        1. dimension_completeness
        2. geometric_constraints
        3. tolerance_verification
        4. manufacturing_readiness
        5. gdt_compliance
    """
    rules: list[VerificationRule] = [
        # 1. dimension_completeness
        SizeDimensionRule(),
        PositionDimensionRule(),
        OverDimensionRule(),
        AngularDimensionRule(),
        # 2. geometric_constraints
        DatumReferenceFrameRule(),
        FeatureOrientationRule(),
        GDTDatumReferenceRule(),
        # 3. tolerance_verification
        DimensionToleranceRule(),
        FCFCompletenessRule(),
        ToleranceStackUpRule(),
        # 4. manufacturing_readiness
        TitleBlockRule(),
        SurfaceFinishRule(),
        HoleSpecificationRule(),
        ViewSufficiencyRule(),
        NoteContradictionRule(),
        # 5. gdt_compliance
        GDTSymbolSetRule(),
        CompositeFCFRule(),
        DatumFeatureSymbolPlacementRule(),
    ]
    return RuleEngine(rules)


def build_verification_report(
    drawing_id: str,
    issues: list[Issue],
    analysis_timestamp: Optional[str] = None,
) -> VerificationReport:
    """Assemble a ``VerificationReport`` from a drawing ID and an issue list.

    Args:
        drawing_id: Identifier for the analyzed drawing (e.g. filename).
        issues: The complete list of ``Issue`` objects produced by the rule engine.
        analysis_timestamp: ISO 8601 timestamp string.  If ``None``, the current
            UTC time is used.

    Returns:
        A fully populated ``VerificationReport`` with:
        - ``overall_status``: ``"Pass"`` if ``len(issues) == 0``, else ``"Fail"``.
        - ``issue_counts``: count of issues per ``Severity`` level.
        - ``systemic_patterns``: summary entries for any ``issue_type`` that
          appears more than three times.
    """
    if analysis_timestamp is None:
        analysis_timestamp = datetime.now(timezone.utc).isoformat()

    overall_status = "Pass" if len(issues) == 0 else "Fail"

    severity_counter: Counter[str] = Counter()
    for sev in Severity:
        severity_counter[sev.value] = 0
    for issue in issues:
        severity_counter[issue.severity.value] += 1
    issue_counts: dict[str, int] = dict(severity_counter)

    type_counter: Counter[str] = Counter(issue.issue_type for issue in issues)
    systemic_patterns: list[str] = []
    for issue_type, count in type_counter.items():
        if count > _SYSTEMIC_PATTERN_THRESHOLD:
            standard_ref = None
            for issue in issues:
                if issue.issue_type == issue_type and issue.standard_reference:
                    standard_ref = issue.standard_reference
                    break
            if standard_ref:
                systemic_patterns.append(
                    f"Systemic pattern detected: '{issue_type}' occurred {count} times "
                    f"(see {standard_ref})"
                )
            else:
                systemic_patterns.append(
                    f"Systemic pattern detected: '{issue_type}' occurred {count} times"
                )

    return VerificationReport(
        drawing_id=drawing_id,
        analysis_timestamp=analysis_timestamp,
        overall_status=overall_status,
        issue_counts=issue_counts,
        issues=issues,
        systemic_patterns=systemic_patterns,
    )
