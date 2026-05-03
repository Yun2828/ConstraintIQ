"""Core data models for the Engineering Drawing Analyzer.

All parsed drawing data is normalized into these dataclasses before any
verification logic runs, so rules are written once regardless of input format.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    """Severity classification for a verification issue."""

    CRITICAL = "Critical"
    WARNING = "Warning"
    INFO = "Info"


class DrawingFormat(str, Enum):
    """Supported input drawing file formats."""

    DXF = "DXF"
    DWG = "DWG"
    PDF = "PDF"


class ReportFormat(str, Enum):
    """Supported output report formats."""

    JSON = "JSON"
    PDF = "PDF"
    HTML = "HTML"


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------


@dataclass
class Point2D:
    """A two-dimensional point in drawing-space coordinates."""

    x: float
    y: float


@dataclass
class LocationReference:
    """A reference to a location on the drawing.

    Attributes:
        view_name:   Name of the view, e.g. "FRONT", "SECTION A-A".
        coordinates: Drawing-space coordinates of the annotation, if available.
        label:       Annotation label (e.g. a dimension tag), if available.
    """

    view_name: str
    coordinates: Optional[Point2D]
    label: Optional[str]


# ---------------------------------------------------------------------------
# Dimensional / tolerance types
# ---------------------------------------------------------------------------


@dataclass
class Tolerance:
    """Permissible variation for a dimension.

    Attributes:
        upper:      Upper deviation (positive).
        lower:      Lower deviation (negative for bilateral, 0 for unilateral).
        is_general: True when this tolerance is inherited from the title block
                    general tolerance block rather than stated explicitly.
    """

    upper: float
    lower: float
    is_general: bool = False


@dataclass
class Dimension:
    """A single annotated dimension on the drawing.

    Attributes:
        id:                     Unique identifier within the GeometricModel.
        value:                  Nominal dimension value.
        unit:                   Unit of measure, e.g. "mm" or "in".
        tolerance:              Associated tolerance, or None if absent.
        location:               Location of the dimension annotation.
        associated_feature_ids: IDs of features this dimension describes.
    """

    id: str
    value: float
    unit: str
    tolerance: Optional[Tolerance]
    location: LocationReference
    associated_feature_ids: list[str] = field(default_factory=list)


@dataclass
class FeatureControlFrame:
    """A GD&T feature control frame annotation.

    Attributes:
        id:                 Unique identifier within the GeometricModel.
        gdt_symbol:         GD&T characteristic symbol, e.g. "⊕" (position).
        tolerance_value:    Tolerance zone value, or None if absent/malformed.
        datum_references:   Ordered list of datum labels, e.g. ["A", "B", "C"].
        material_condition: Material condition modifier: "MMC", "LMC", or "RFS".
        location:           Location of the feature control frame on the drawing.
    """

    id: str
    gdt_symbol: str
    tolerance_value: Optional[float]
    datum_references: list[str]
    material_condition: Optional[str]
    location: LocationReference


@dataclass
class Datum:
    """A datum feature definition.

    Attributes:
        label:      Datum identifier, e.g. "A", "B", "C".
        feature_id: ID of the Feature this datum is applied to.
        location:   Location of the datum feature symbol on the drawing.
    """

    label: str
    feature_id: str
    location: LocationReference


# ---------------------------------------------------------------------------
# Feature
# ---------------------------------------------------------------------------


@dataclass
class Feature:
    """A discrete geometric element on the drawing.

    Attributes:
        id:                   Unique identifier within the GeometricModel.
        feature_type:         Semantic type, e.g. "HOLE", "SLOT", "SURFACE".
        dimensions:           Dimensions that describe this feature.
        feature_control_frames: GD&T annotations applied to this feature.
        location:             Location reference for the feature on the drawing.
        is_angular:           True if this is an angular feature (chamfer, taper, etc.).
        is_threaded:          True if this is a threaded feature.
        is_blind_hole:        True if this is a blind hole.
        ml_confidence:        Confidence score when feature_type was assigned by the
                              DPSS ML model; None for heuristically parsed features.
        ml_symbol_type:       Raw DPSS symbol category label, if applicable.
    """

    id: str
    feature_type: str
    dimensions: list[Dimension] = field(default_factory=list)
    feature_control_frames: list[FeatureControlFrame] = field(default_factory=list)
    location: Optional[LocationReference] = None
    is_angular: bool = False
    is_threaded: bool = False
    is_blind_hole: bool = False
    ml_confidence: Optional[float] = None
    ml_symbol_type: Optional[str] = None


# ---------------------------------------------------------------------------
# Title block and views
# ---------------------------------------------------------------------------


@dataclass
class TitleBlock:
    """Structured data extracted from the drawing title block.

    All fields are Optional because they may be absent in a malformed drawing;
    the manufacturing-readiness rule engine checks for missing required fields.
    """

    part_number: Optional[str]
    revision: Optional[str]
    material: Optional[str]
    scale: Optional[str]
    units: Optional[str]


@dataclass
class View:
    """An orthographic or section view on the drawing.

    Attributes:
        name:     View identifier, e.g. "FRONT", "TOP", "SECTION A-A".
        features: IDs of features visible in this view.
    """

    name: str
    features: list[str]


# ---------------------------------------------------------------------------
# Geometric model (the normalized internal representation)
# ---------------------------------------------------------------------------


@dataclass
class GeometricModel:
    """The normalized internal representation of a parsed engineering drawing.

    All parsers (DXF, DWG, PDF) produce a GeometricModel; all rule engine
    modules consume a GeometricModel.  This ensures rules are written once.

    Attributes:
        schema_version:        Version string for serialization compatibility.
        source_format:         The input format this model was parsed from.
        features:              All geometric features on the drawing.
        dimensions:            All dimension annotations (top-level; features
                               also carry their own dimension lists).
        datums:                All datum feature definitions.
        feature_control_frames: All GD&T feature control frames (top-level).
        title_block:           Extracted title block data, or None if absent.
        views:                 All orthographic/section views.
        general_tolerance:     Drawing-level general tolerance block, or None.
        notes:                 Free-text notes and specifications on the drawing.
    """

    schema_version: str = "1.0"
    source_format: DrawingFormat = DrawingFormat.DXF
    features: list[Feature] = field(default_factory=list)
    dimensions: list[Dimension] = field(default_factory=list)
    datums: list[Datum] = field(default_factory=list)
    feature_control_frames: list[FeatureControlFrame] = field(default_factory=list)
    title_block: Optional[TitleBlock] = None
    views: list[View] = field(default_factory=list)
    general_tolerance: Optional[Tolerance] = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Issue and verification report
# ---------------------------------------------------------------------------


@dataclass
class Issue:
    """A single deficiency found by the rule engine.

    Attributes:
        issue_id:           Unique identifier for this issue instance.
        rule_id:            Identifier of the rule that produced this issue.
        issue_type:         Machine-readable issue category, e.g.
                            "MISSING_SIZE_DIMENSION".
        severity:           Impact classification (Critical / Warning / Info).
        description:        Human-readable description of the deficiency.
        location:           Location of the deficiency on the drawing.
        corrective_action:  Suggested fix; required for Critical issues.
        standard_reference: Applicable ANSI/ASME Y14.5 clause, if relevant.
    """

    issue_id: str
    rule_id: str
    issue_type: str
    severity: Severity
    description: str
    location: LocationReference
    corrective_action: Optional[str] = None
    standard_reference: Optional[str] = None


@dataclass
class VerificationReport:
    """The structured output produced after analyzing a drawing.

    Attributes:
        drawing_id:         Identifier for the analyzed drawing (e.g. filename).
        analysis_timestamp: ISO 8601 timestamp of when analysis completed.
        overall_status:     "Pass" if no issues were found, otherwise "Fail".
        issue_counts:       Count of issues per severity level, e.g.
                            {"Critical": 2, "Warning": 1, "Info": 0}.
        issues:             Full list of all issues found.
        systemic_patterns:  Summary notes for repeated issue types (generated
                            when more than three issues share the same type).
    """

    drawing_id: str
    analysis_timestamp: str
    overall_status: str
    issue_counts: dict[str, int]
    issues: list[Issue]
    systemic_patterns: list[str]
