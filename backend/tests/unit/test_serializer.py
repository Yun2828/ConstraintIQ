"""Unit tests for GeometricModelSerializer.

Tests serialization of a fully-populated GeometricModel fixture,
deserialization of a known JSON dict, and schema_version preservation.

Requirements: 1.5, 1.6
"""

import json

import pytest

from engineering_drawing_analyzer.models import (
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
from engineering_drawing_analyzer.serializer import (
    GeometricModelSerializer,
    models_equivalent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_full_model() -> GeometricModel:
    """Return a fully-populated GeometricModel for use in tests."""
    loc = LocationReference(
        view_name="FRONT",
        coordinates=Point2D(x=10.0, y=20.0),
        label="D1",
    )
    tol = Tolerance(upper=0.1, lower=-0.1, is_general=False)
    dim = Dimension(
        id="dim-1",
        value=25.4,
        unit="mm",
        tolerance=tol,
        location=loc,
        associated_feature_ids=["feat-1"],
    )
    fcf = FeatureControlFrame(
        id="fcf-1",
        gdt_symbol="⊕",
        tolerance_value=0.05,
        datum_references=["A", "B"],
        material_condition="MMC",
        location=loc,
    )
    datum = Datum(label="A", feature_id="feat-1", location=loc)
    feature = Feature(
        id="feat-1",
        feature_type="HOLE",
        dimensions=[dim],
        feature_control_frames=[fcf],
        location=loc,
        is_angular=False,
        is_threaded=True,
        is_blind_hole=True,
        ml_confidence=0.95,
        ml_symbol_type="HOLE_CALLOUT",
    )
    title_block = TitleBlock(
        part_number="PN-001",
        revision="A",
        material="STEEL",
        scale="1:1",
        units="mm",
    )
    view = View(name="FRONT", features=["feat-1"])
    general_tol = Tolerance(upper=0.2, lower=-0.2, is_general=True)

    return GeometricModel(
        schema_version="1.0",
        source_format=DrawingFormat.DXF,
        features=[feature],
        dimensions=[dim],
        datums=[datum],
        feature_control_frames=[fcf],
        title_block=title_block,
        views=[view],
        general_tolerance=general_tol,
        notes=["ALL DIMENSIONS IN MM", "REMOVE BURRS"],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSerialize:
    def test_serialize_returns_dict(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        assert isinstance(result, dict)

    def test_serialize_is_json_serializable(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        # Should not raise
        json_str = json.dumps(result)
        assert isinstance(json_str, str)

    def test_serialize_schema_version(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        assert result["schema_version"] == "1.0"

    def test_serialize_source_format_as_string_name(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        # Enum stored as its name, not value
        assert result["source_format"] == "DXF"
        assert isinstance(result["source_format"], str)

    def test_serialize_features_list(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        assert len(result["features"]) == 1
        feat = result["features"][0]
        assert feat["id"] == "feat-1"
        assert feat["feature_type"] == "HOLE"
        assert feat["is_threaded"] is True
        assert feat["is_blind_hole"] is True
        assert feat["ml_confidence"] == pytest.approx(0.95)
        assert feat["ml_symbol_type"] == "HOLE_CALLOUT"

    def test_serialize_dimensions_list(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        assert len(result["dimensions"]) == 1
        dim = result["dimensions"][0]
        assert dim["id"] == "dim-1"
        assert dim["value"] == pytest.approx(25.4)
        assert dim["unit"] == "mm"
        assert dim["tolerance"]["upper"] == pytest.approx(0.1)
        assert dim["tolerance"]["lower"] == pytest.approx(-0.1)
        assert dim["tolerance"]["is_general"] is False

    def test_serialize_coordinates_as_float_list(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        dim = result["dimensions"][0]
        coords = dim["location"]["coordinates"]
        assert isinstance(coords, list)
        assert len(coords) == 2
        assert coords[0] == pytest.approx(10.0)
        assert coords[1] == pytest.approx(20.0)

    def test_serialize_title_block(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        tb = result["title_block"]
        assert tb["part_number"] == "PN-001"
        assert tb["revision"] == "A"
        assert tb["material"] == "STEEL"
        assert tb["scale"] == "1:1"
        assert tb["units"] == "mm"

    def test_serialize_notes(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        assert result["notes"] == ["ALL DIMENSIONS IN MM", "REMOVE BURRS"]

    def test_serialize_general_tolerance(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        gt = result["general_tolerance"]
        assert gt["upper"] == pytest.approx(0.2)
        assert gt["lower"] == pytest.approx(-0.2)
        assert gt["is_general"] is True

    def test_serialize_none_title_block(self) -> None:
        model = GeometricModel()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        assert result["title_block"] is None

    def test_serialize_none_general_tolerance(self) -> None:
        model = GeometricModel()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        assert result["general_tolerance"] is None

    def test_serialize_feature_control_frame(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        fcf = result["feature_control_frames"][0]
        assert fcf["id"] == "fcf-1"
        assert fcf["gdt_symbol"] == "⊕"
        assert fcf["tolerance_value"] == pytest.approx(0.05)
        assert fcf["datum_references"] == ["A", "B"]
        assert fcf["material_condition"] == "MMC"

    def test_serialize_datums(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        datum = result["datums"][0]
        assert datum["label"] == "A"
        assert datum["feature_id"] == "feat-1"

    def test_serialize_views(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        result = serializer.serialize(model)
        view = result["views"][0]
        assert view["name"] == "FRONT"
        assert view["features"] == ["feat-1"]


class TestDeserialize:
    def test_deserialize_returns_geometric_model(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        data = serializer.serialize(model)
        restored = serializer.deserialize(data)
        assert isinstance(restored, GeometricModel)

    def test_deserialize_schema_version_preserved(self) -> None:
        data = {
            "schema_version": "1.0",
            "source_format": "PDF",
            "features": [],
            "dimensions": [],
            "datums": [],
            "feature_control_frames": [],
            "title_block": None,
            "views": [],
            "general_tolerance": None,
            "notes": [],
        }
        serializer = GeometricModelSerializer()
        model = serializer.deserialize(data)
        assert model.schema_version == "1.0"

    def test_deserialize_source_format_enum(self) -> None:
        data = {
            "schema_version": "1.0",
            "source_format": "PDF",
            "features": [],
            "dimensions": [],
            "datums": [],
            "feature_control_frames": [],
            "title_block": None,
            "views": [],
            "general_tolerance": None,
            "notes": [],
        }
        serializer = GeometricModelSerializer()
        model = serializer.deserialize(data)
        assert model.source_format == DrawingFormat.PDF

    def test_deserialize_known_dict(self) -> None:
        """Deserialize a hand-crafted dict and verify field values."""
        data = {
            "schema_version": "1.0",
            "source_format": "DXF",
            "features": [
                {
                    "id": "f1",
                    "feature_type": "SLOT",
                    "dimensions": [],
                    "feature_control_frames": [],
                    "location": None,
                    "is_angular": True,
                    "is_threaded": False,
                    "is_blind_hole": False,
                    "ml_confidence": None,
                    "ml_symbol_type": None,
                }
            ],
            "dimensions": [],
            "datums": [],
            "feature_control_frames": [],
            "title_block": {
                "part_number": "X-42",
                "revision": "B",
                "material": "ALUMINUM",
                "scale": "2:1",
                "units": "in",
            },
            "views": [],
            "general_tolerance": None,
            "notes": ["NOTE 1"],
        }
        serializer = GeometricModelSerializer()
        model = serializer.deserialize(data)

        assert len(model.features) == 1
        feat = model.features[0]
        assert feat.id == "f1"
        assert feat.feature_type == "SLOT"
        assert feat.is_angular is True
        assert feat.location is None

        assert model.title_block is not None
        assert model.title_block.part_number == "X-42"
        assert model.title_block.revision == "B"
        assert model.notes == ["NOTE 1"]

    def test_deserialize_with_coordinates(self) -> None:
        data = {
            "schema_version": "1.0",
            "source_format": "DXF",
            "features": [],
            "dimensions": [
                {
                    "id": "d1",
                    "value": 50.0,
                    "unit": "mm",
                    "tolerance": None,
                    "location": {
                        "view_name": "TOP",
                        "coordinates": [5.0, 15.0],
                        "label": None,
                    },
                    "associated_feature_ids": [],
                }
            ],
            "datums": [],
            "feature_control_frames": [],
            "title_block": None,
            "views": [],
            "general_tolerance": None,
            "notes": [],
        }
        serializer = GeometricModelSerializer()
        model = serializer.deserialize(data)

        dim = model.dimensions[0]
        assert dim.id == "d1"
        assert dim.value == pytest.approx(50.0)
        assert dim.location.view_name == "TOP"
        assert dim.location.coordinates is not None
        assert dim.location.coordinates.x == pytest.approx(5.0)
        assert dim.location.coordinates.y == pytest.approx(15.0)

    def test_deserialize_defaults_for_missing_optional_keys(self) -> None:
        """Deserializer should handle missing optional keys gracefully."""
        data = {
            "source_format": "DWG",
            # schema_version missing — should default to SCHEMA_VERSION
        }
        serializer = GeometricModelSerializer()
        model = serializer.deserialize(data)
        assert model.schema_version == "1.0"
        assert model.source_format == DrawingFormat.DWG
        assert model.features == []
        assert model.notes == []


class TestSchemaVersionPreservation:
    def test_schema_version_survives_round_trip(self) -> None:
        model = GeometricModel(schema_version="1.0", source_format=DrawingFormat.DXF)
        serializer = GeometricModelSerializer()
        data = serializer.serialize(model)
        restored = serializer.deserialize(data)
        assert restored.schema_version == model.schema_version

    def test_custom_schema_version_preserved(self) -> None:
        """A non-default schema_version written by serialize() is read back correctly."""
        model = GeometricModel(schema_version="2.0", source_format=DrawingFormat.PDF)
        serializer = GeometricModelSerializer()
        data = serializer.serialize(model)
        # The serializer writes model.schema_version, not the constant
        assert data["schema_version"] == "2.0"
        restored = serializer.deserialize(data)
        assert restored.schema_version == "2.0"


class TestModelsEquivalent:
    def test_equivalent_empty_models(self) -> None:
        a = GeometricModel()
        b = GeometricModel()
        assert models_equivalent(a, b)

    def test_equivalent_full_models(self) -> None:
        a = make_full_model()
        b = make_full_model()
        assert models_equivalent(a, b)

    def test_not_equivalent_different_format(self) -> None:
        a = GeometricModel(source_format=DrawingFormat.DXF)
        b = GeometricModel(source_format=DrawingFormat.PDF)
        assert not models_equivalent(a, b)

    def test_not_equivalent_different_notes(self) -> None:
        a = GeometricModel(notes=["note A"])
        b = GeometricModel(notes=["note B"])
        assert not models_equivalent(a, b)

    def test_not_equivalent_different_feature_count(self) -> None:
        loc = LocationReference(view_name="FRONT", coordinates=None, label=None)
        feat = Feature(id="f1", feature_type="HOLE")
        a = GeometricModel(features=[feat])
        b = GeometricModel(features=[])
        assert not models_equivalent(a, b)

    def test_round_trip_produces_equivalent_model(self) -> None:
        model = make_full_model()
        serializer = GeometricModelSerializer()
        data = serializer.serialize(model)
        restored = serializer.deserialize(data)
        assert models_equivalent(model, restored)
