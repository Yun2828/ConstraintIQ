"""Serializer for GeometricModel — converts to/from JSON-serializable dicts.

The serialized format uses a ``schema_version`` field to support future
migrations.  All geometry coordinates are stored as lists of floats.
Enumerations are stored as their string names (enum member names, not values).
"""

from __future__ import annotations

from typing import Any, Optional

from .models import (
    Datum,
    Dimension,
    DrawingFormat,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    LocationReference,
    Point2D,
    TitleBlock,
    Tolerance,
    View,
)

# ---------------------------------------------------------------------------
# Current schema version written by serialize(); deserialize() accepts this.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "1.0"


class GeometricModelSerializer:
    """Serializes and deserializes :class:`GeometricModel` instances."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def serialize(self, model: GeometricModel) -> dict:
        """Convert *model* to a JSON-serializable :class:`dict`.

        The returned dict can be passed directly to :func:`json.dumps`.
        """
        return {
            "schema_version": model.schema_version,
            "source_format": model.source_format.name,
            "features": [self._serialize_feature(f) for f in model.features],
            "dimensions": [self._serialize_dimension(d) for d in model.dimensions],
            "datums": [self._serialize_datum(d) for d in model.datums],
            "feature_control_frames": [
                self._serialize_fcf(fcf) for fcf in model.feature_control_frames
            ],
            "title_block": self._serialize_title_block(model.title_block),
            "views": [self._serialize_view(v) for v in model.views],
            "general_tolerance": self._serialize_tolerance(model.general_tolerance),
            "notes": list(model.notes),
        }

    def deserialize(self, data: dict) -> GeometricModel:
        """Reconstruct a :class:`GeometricModel` from a previously serialized dict."""
        return GeometricModel(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            source_format=DrawingFormat[data["source_format"]],
            features=[self._deserialize_feature(f) for f in data.get("features", [])],
            dimensions=[
                self._deserialize_dimension(d) for d in data.get("dimensions", [])
            ],
            datums=[self._deserialize_datum(d) for d in data.get("datums", [])],
            feature_control_frames=[
                self._deserialize_fcf(fcf)
                for fcf in data.get("feature_control_frames", [])
            ],
            title_block=self._deserialize_title_block(data.get("title_block")),
            views=[self._deserialize_view(v) for v in data.get("views", [])],
            general_tolerance=self._deserialize_tolerance(
                data.get("general_tolerance")
            ),
            notes=list(data.get("notes", [])),
        )

    # ------------------------------------------------------------------
    # Primitive serializers
    # ------------------------------------------------------------------

    def _serialize_point(self, point: Optional[Point2D]) -> Optional[list[float]]:
        if point is None:
            return None
        return [point.x, point.y]

    def _deserialize_point(self, data: Optional[list[float]]) -> Optional[Point2D]:
        if data is None:
            return None
        return Point2D(x=data[0], y=data[1])

    def _serialize_location(self, loc: LocationReference) -> dict:
        return {
            "view_name": loc.view_name,
            "coordinates": self._serialize_point(loc.coordinates),
            "label": loc.label,
        }

    def _deserialize_location(self, data: dict) -> LocationReference:
        return LocationReference(
            view_name=data["view_name"],
            coordinates=self._deserialize_point(data.get("coordinates")),
            label=data.get("label"),
        )

    def _serialize_tolerance(self, tol: Optional[Tolerance]) -> Optional[dict]:
        if tol is None:
            return None
        return {
            "upper": tol.upper,
            "lower": tol.lower,
            "is_general": tol.is_general,
        }

    def _deserialize_tolerance(self, data: Optional[dict]) -> Optional[Tolerance]:
        if data is None:
            return None
        return Tolerance(
            upper=data["upper"],
            lower=data["lower"],
            is_general=data.get("is_general", False),
        )

    # ------------------------------------------------------------------
    # Dimension
    # ------------------------------------------------------------------

    def _serialize_dimension(self, dim: Dimension) -> dict:
        return {
            "id": dim.id,
            "value": dim.value,
            "unit": dim.unit,
            "tolerance": self._serialize_tolerance(dim.tolerance),
            "location": self._serialize_location(dim.location),
            "associated_feature_ids": list(dim.associated_feature_ids),
        }

    def _deserialize_dimension(self, data: dict) -> Dimension:
        return Dimension(
            id=data["id"],
            value=data["value"],
            unit=data["unit"],
            tolerance=self._deserialize_tolerance(data.get("tolerance")),
            location=self._deserialize_location(data["location"]),
            associated_feature_ids=list(data.get("associated_feature_ids", [])),
        )

    # ------------------------------------------------------------------
    # FeatureControlFrame
    # ------------------------------------------------------------------

    def _serialize_fcf(self, fcf: FeatureControlFrame) -> dict:
        return {
            "id": fcf.id,
            "gdt_symbol": fcf.gdt_symbol,
            "tolerance_value": fcf.tolerance_value,
            "datum_references": list(fcf.datum_references),
            "material_condition": fcf.material_condition,
            "location": self._serialize_location(fcf.location),
        }

    def _deserialize_fcf(self, data: dict) -> FeatureControlFrame:
        return FeatureControlFrame(
            id=data["id"],
            gdt_symbol=data["gdt_symbol"],
            tolerance_value=data.get("tolerance_value"),
            datum_references=list(data.get("datum_references", [])),
            material_condition=data.get("material_condition"),
            location=self._deserialize_location(data["location"]),
        )

    # ------------------------------------------------------------------
    # Datum
    # ------------------------------------------------------------------

    def _serialize_datum(self, datum: Datum) -> dict:
        return {
            "label": datum.label,
            "feature_id": datum.feature_id,
            "location": self._serialize_location(datum.location),
        }

    def _deserialize_datum(self, data: dict) -> Datum:
        return Datum(
            label=data["label"],
            feature_id=data["feature_id"],
            location=self._deserialize_location(data["location"]),
        )

    # ------------------------------------------------------------------
    # Feature
    # ------------------------------------------------------------------

    def _serialize_feature(self, feature: Feature) -> dict:
        return {
            "id": feature.id,
            "feature_type": feature.feature_type,
            "dimensions": [self._serialize_dimension(d) for d in feature.dimensions],
            "feature_control_frames": [
                self._serialize_fcf(fcf) for fcf in feature.feature_control_frames
            ],
            "location": (
                self._serialize_location(feature.location)
                if feature.location is not None
                else None
            ),
            "is_angular": feature.is_angular,
            "is_threaded": feature.is_threaded,
            "is_blind_hole": feature.is_blind_hole,
            "ml_confidence": feature.ml_confidence,
            "ml_symbol_type": feature.ml_symbol_type,
        }

    def _deserialize_feature(self, data: dict) -> Feature:
        loc_data = data.get("location")
        return Feature(
            id=data["id"],
            feature_type=data["feature_type"],
            dimensions=[
                self._deserialize_dimension(d) for d in data.get("dimensions", [])
            ],
            feature_control_frames=[
                self._deserialize_fcf(fcf)
                for fcf in data.get("feature_control_frames", [])
            ],
            location=(
                self._deserialize_location(loc_data) if loc_data is not None else None
            ),
            is_angular=data.get("is_angular", False),
            is_threaded=data.get("is_threaded", False),
            is_blind_hole=data.get("is_blind_hole", False),
            ml_confidence=data.get("ml_confidence"),
            ml_symbol_type=data.get("ml_symbol_type"),
        )

    # ------------------------------------------------------------------
    # TitleBlock
    # ------------------------------------------------------------------

    def _serialize_title_block(self, tb: Optional[TitleBlock]) -> Optional[dict]:
        if tb is None:
            return None
        return {
            "part_number": tb.part_number,
            "revision": tb.revision,
            "material": tb.material,
            "scale": tb.scale,
            "units": tb.units,
        }

    def _deserialize_title_block(self, data: Optional[dict]) -> Optional[TitleBlock]:
        if data is None:
            return None
        return TitleBlock(
            part_number=data.get("part_number"),
            revision=data.get("revision"),
            material=data.get("material"),
            scale=data.get("scale"),
            units=data.get("units"),
        )

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    def _serialize_view(self, view: View) -> dict:
        return {
            "name": view.name,
            "features": list(view.features),
        }

    def _deserialize_view(self, data: dict) -> View:
        return View(
            name=data["name"],
            features=list(data.get("features", [])),
        )


# ---------------------------------------------------------------------------
# Structural equality helper
# ---------------------------------------------------------------------------


def models_equivalent(a: GeometricModel, b: GeometricModel) -> bool:
    """Return True if *a* and *b* are structurally equivalent.

    This performs a deep field-by-field comparison rather than relying on
    Python's default dataclass ``__eq__`` (which compares by identity for
    mutable fields in some edge cases).  It is the canonical equality check
    used in round-trip property tests.
    """
    if a.schema_version != b.schema_version:
        return False
    if a.source_format != b.source_format:
        return False
    if a.notes != b.notes:
        return False
    if not _tolerances_equal(a.general_tolerance, b.general_tolerance):
        return False
    if not _title_blocks_equal(a.title_block, b.title_block):
        return False
    if len(a.features) != len(b.features):
        return False
    for fa, fb in zip(a.features, b.features):
        if not _features_equal(fa, fb):
            return False
    if len(a.dimensions) != len(b.dimensions):
        return False
    for da, db in zip(a.dimensions, b.dimensions):
        if not _dimensions_equal(da, db):
            return False
    if len(a.datums) != len(b.datums):
        return False
    for da, db in zip(a.datums, b.datums):
        if not _datums_equal(da, db):
            return False
    if len(a.feature_control_frames) != len(b.feature_control_frames):
        return False
    for fa, fb in zip(a.feature_control_frames, b.feature_control_frames):
        if not _fcfs_equal(fa, fb):
            return False
    if len(a.views) != len(b.views):
        return False
    for va, vb in zip(a.views, b.views):
        if not _views_equal(va, vb):
            return False
    return True


# ---------------------------------------------------------------------------
# Private comparison helpers
# ---------------------------------------------------------------------------


def _points_equal(a: Optional[Point2D], b: Optional[Point2D]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a.x == b.x and a.y == b.y


def _locations_equal(a: LocationReference, b: LocationReference) -> bool:
    return (
        a.view_name == b.view_name
        and _points_equal(a.coordinates, b.coordinates)
        and a.label == b.label
    )


def _tolerances_equal(a: Optional[Tolerance], b: Optional[Tolerance]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return a.upper == b.upper and a.lower == b.lower and a.is_general == b.is_general


def _dimensions_equal(a: Dimension, b: Dimension) -> bool:
    return (
        a.id == b.id
        and a.value == b.value
        and a.unit == b.unit
        and _tolerances_equal(a.tolerance, b.tolerance)
        and _locations_equal(a.location, b.location)
        and a.associated_feature_ids == b.associated_feature_ids
    )


def _fcfs_equal(a: FeatureControlFrame, b: FeatureControlFrame) -> bool:
    return (
        a.id == b.id
        and a.gdt_symbol == b.gdt_symbol
        and a.tolerance_value == b.tolerance_value
        and a.datum_references == b.datum_references
        and a.material_condition == b.material_condition
        and _locations_equal(a.location, b.location)
    )


def _datums_equal(a: Datum, b: Datum) -> bool:
    return (
        a.label == b.label
        and a.feature_id == b.feature_id
        and _locations_equal(a.location, b.location)
    )


def _features_equal(a: Feature, b: Feature) -> bool:
    if a.id != b.id:
        return False
    if a.feature_type != b.feature_type:
        return False
    if a.is_angular != b.is_angular:
        return False
    if a.is_threaded != b.is_threaded:
        return False
    if a.is_blind_hole != b.is_blind_hole:
        return False
    if a.ml_confidence != b.ml_confidence:
        return False
    if a.ml_symbol_type != b.ml_symbol_type:
        return False
    loc_ok = (a.location is None and b.location is None) or (
        a.location is not None
        and b.location is not None
        and _locations_equal(a.location, b.location)
    )
    if not loc_ok:
        return False
    if len(a.dimensions) != len(b.dimensions):
        return False
    for da, db in zip(a.dimensions, b.dimensions):
        if not _dimensions_equal(da, db):
            return False
    if len(a.feature_control_frames) != len(b.feature_control_frames):
        return False
    for fa, fb in zip(a.feature_control_frames, b.feature_control_frames):
        if not _fcfs_equal(fa, fb):
            return False
    return True


def _title_blocks_equal(a: Optional[TitleBlock], b: Optional[TitleBlock]) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return (
        a.part_number == b.part_number
        and a.revision == b.revision
        and a.material == b.material
        and a.scale == b.scale
        and a.units == b.units
    )


def _views_equal(a: View, b: View) -> bool:
    return a.name == b.name and a.features == b.features
