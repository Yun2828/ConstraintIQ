"""Unit tests for the DXF Parser.

Tests:
- Parsing a minimal valid DXF fixture with known dimensions and GD&T annotations
- Parsing geometry entities (LINE, ARC, CIRCLE, LWPOLYLINE) into Features
- Extracting DIMENSION entities into Dimension objects
- Extracting TOLERANCE entities into FeatureControlFrame objects
- Extracting INSERT entities referencing title blocks into TitleBlock
- Extracting TEXT/MTEXT entities into notes
- Corrupted DXF raises ParseError with location info

Requirements: 1.2, 1.3
"""

from __future__ import annotations

import io
import textwrap
from typing import Optional

import ezdxf
import pytest

from engineering_drawing_analyzer.exceptions import ParseError
from engineering_drawing_analyzer.models import (
    DrawingFormat,
    FeatureControlFrame,
    GeometricModel,
)
from engineering_drawing_analyzer.parsers.dxf_parser import DXFParser, _parse_tolerance_string


# ---------------------------------------------------------------------------
# Helpers — build minimal DXF bytes in memory using ezdxf
# ---------------------------------------------------------------------------


def _make_dxf_bytes(**kwargs) -> bytes:
    """Create a minimal DXF document and return its bytes.

    Keyword arguments are passed to a builder function that populates the
    modelspace.  The builder receives the ezdxf document object.
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    builder = kwargs.get("builder")
    if builder is not None:
        builder(doc, msp)
    # ezdxf.write() requires a text stream; encode to bytes afterwards
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Basic parsing — empty drawing
# ---------------------------------------------------------------------------


class TestDXFParserBasic:
    def test_parse_empty_drawing_returns_geometric_model(self) -> None:
        """Parsing an empty DXF should return a GeometricModel with DXF format."""
        data = _make_dxf_bytes()
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert isinstance(model, GeometricModel)
        assert model.source_format == DrawingFormat.DXF
        assert model.schema_version == "1.0"

    def test_parse_empty_drawing_has_no_features(self) -> None:
        """An empty DXF should produce no features."""
        data = _make_dxf_bytes()
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert model.features == []

    def test_parse_empty_drawing_has_no_dimensions(self) -> None:
        """An empty DXF should produce no dimensions."""
        data = _make_dxf_bytes()
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert model.dimensions == []


# ---------------------------------------------------------------------------
# Geometry entity extraction
# ---------------------------------------------------------------------------


class TestGeometryExtraction:
    def test_line_entity_creates_edge_feature(self) -> None:
        """A LINE entity should produce a Feature with feature_type 'EDGE'."""
        def builder(doc, msp):
            msp.add_line((0, 0), (10, 0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert any(f.feature_type == "EDGE" for f in model.features)

    def test_arc_entity_creates_arc_feature(self) -> None:
        """An ARC entity should produce a Feature with feature_type 'ARC'."""
        def builder(doc, msp):
            msp.add_arc(center=(5, 5), radius=3, start_angle=0, end_angle=90)

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert any(f.feature_type == "ARC" for f in model.features)

    def test_circle_entity_creates_circle_feature(self) -> None:
        """A CIRCLE entity should produce a Feature with feature_type 'CIRCLE'."""
        def builder(doc, msp):
            msp.add_circle(center=(5, 5), radius=3)

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert any(f.feature_type == "CIRCLE" for f in model.features)

    def test_lwpolyline_entity_creates_polyline_feature(self) -> None:
        """An LWPOLYLINE entity should produce a Feature with feature_type 'POLYLINE'."""
        def builder(doc, msp):
            msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert any(f.feature_type == "POLYLINE" for f in model.features)

    def test_multiple_geometry_entities(self) -> None:
        """Multiple geometry entities should all produce Feature objects."""
        def builder(doc, msp):
            msp.add_line((0, 0), (10, 0))
            msp.add_circle(center=(5, 5), radius=2)
            msp.add_arc(center=(0, 0), radius=5, start_angle=0, end_angle=180)

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.features) == 3

    def test_feature_has_unique_ids(self) -> None:
        """Each Feature should have a unique ID."""
        def builder(doc, msp):
            msp.add_line((0, 0), (10, 0))
            msp.add_line((0, 5), (10, 5))
            msp.add_circle(center=(5, 5), radius=2)

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        ids = [f.id for f in model.features]
        assert len(ids) == len(set(ids)), "Feature IDs must be unique"

    def test_feature_location_is_set(self) -> None:
        """Features extracted from geometry entities should have a location."""
        def builder(doc, msp):
            msp.add_line((3.0, 4.0), (10.0, 4.0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.features) == 1
        feature = model.features[0]
        assert feature.location is not None
        # The start point of the line should be the location
        assert feature.location.coordinates is not None
        assert feature.location.coordinates.x == pytest.approx(3.0)
        assert feature.location.coordinates.y == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# DIMENSION entity extraction
# ---------------------------------------------------------------------------


class TestDimensionExtraction:
    def test_dimension_entity_creates_dimension(self) -> None:
        """A DIMENSION entity should produce a Dimension object."""
        def builder(doc, msp):
            msp.add_linear_dim(
                base=(0, 3),
                p1=(0, 0),
                p2=(10, 0),
                dimstyle="Standard",
            ).render()

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.dimensions) >= 1

    def test_dimension_has_unique_id(self) -> None:
        """Each Dimension should have a unique ID."""
        def builder(doc, msp):
            msp.add_linear_dim(base=(0, 3), p1=(0, 0), p2=(10, 0)).render()
            msp.add_linear_dim(base=(0, 6), p1=(0, 0), p2=(20, 0)).render()

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        ids = [d.id for d in model.dimensions]
        assert len(ids) == len(set(ids)), "Dimension IDs must be unique"

    def test_dimension_unit_reflects_insunits(self) -> None:
        """Dimension unit should reflect the drawing's $INSUNITS setting."""
        def builder(doc, msp):
            # Set $INSUNITS to 4 (millimetres)
            doc.header["$INSUNITS"] = 4
            msp.add_linear_dim(base=(0, 3), p1=(0, 0), p2=(10, 0)).render()

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.dimensions) >= 1
        assert model.dimensions[0].unit == "mm"

    def test_dimension_unit_inches(self) -> None:
        """Dimension unit should be 'in' when $INSUNITS is 1."""
        def builder(doc, msp):
            doc.header["$INSUNITS"] = 1
            msp.add_linear_dim(base=(0, 3), p1=(0, 0), p2=(10, 0)).render()

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.dimensions) >= 1
        assert model.dimensions[0].unit == "in"

    def test_dimension_location_is_set(self) -> None:
        """Dimension objects should have a location reference."""
        def builder(doc, msp):
            msp.add_linear_dim(base=(0, 3), p1=(0, 0), p2=(10, 0)).render()

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.dimensions) >= 1
        assert model.dimensions[0].location is not None


# ---------------------------------------------------------------------------
# TOLERANCE entity extraction (GD&T FCF)
# ---------------------------------------------------------------------------


class TestToleranceExtraction:
    def test_tolerance_entity_creates_fcf(self) -> None:
        """A TOLERANCE entity should produce a FeatureControlFrame."""
        def builder(doc, msp):
            # Add a TOLERANCE entity with a position FCF string
            # {GDT;10} = position symbol, 0.1 = tolerance value, A = datum
            # ezdxf uses new_entity() for TOLERANCE; attribute is 'content' not 'string'
            msp.new_entity(
                "TOLERANCE",
                dxfattribs={"content": "{GDT;10}|0.1|A", "insert": (5, 5)},
            )

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.feature_control_frames) >= 1

    def test_tolerance_fcf_has_unique_id(self) -> None:
        """Each FeatureControlFrame should have a unique ID."""
        def builder(doc, msp):
            msp.new_entity("TOLERANCE", dxfattribs={"content": "{GDT;10}|0.1|A", "insert": (5, 5)})
            msp.new_entity("TOLERANCE", dxfattribs={"content": "{GDT;8}|0.05|B", "insert": (10, 5)})

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        ids = [fcf.id for fcf in model.feature_control_frames]
        assert len(ids) == len(set(ids)), "FCF IDs must be unique"

    def test_tolerance_fcf_gdt_symbol_extracted(self) -> None:
        """The GD&T symbol should be extracted from the tolerance string."""
        def builder(doc, msp):
            # {GDT;10} = position (⊕)
            msp.new_entity("TOLERANCE", dxfattribs={"content": "{GDT;10}|0.1|A", "insert": (5, 5)})

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.feature_control_frames) >= 1
        fcf = model.feature_control_frames[0]
        assert fcf.gdt_symbol == "⊕"

    def test_tolerance_fcf_datum_references_extracted(self) -> None:
        """Datum references should be extracted from the tolerance string."""
        def builder(doc, msp):
            msp.new_entity("TOLERANCE", dxfattribs={"content": "{GDT;10}|0.1|A|B", "insert": (5, 5)})

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.feature_control_frames) >= 1
        fcf = model.feature_control_frames[0]
        assert "A" in fcf.datum_references
        assert "B" in fcf.datum_references

    def test_tolerance_fcf_location_is_set(self) -> None:
        """FeatureControlFrame should have a location reference."""
        def builder(doc, msp):
            msp.new_entity("TOLERANCE", dxfattribs={"content": "{GDT;10}|0.1|A", "insert": (7.0, 3.0)})

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert len(model.feature_control_frames) >= 1
        fcf = model.feature_control_frames[0]
        assert fcf.location is not None
        assert fcf.location.coordinates is not None
        assert fcf.location.coordinates.x == pytest.approx(7.0)
        assert fcf.location.coordinates.y == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# INSERT entity → TitleBlock extraction
# ---------------------------------------------------------------------------


class TestTitleBlockExtraction:
    def test_insert_with_title_in_name_creates_title_block(self) -> None:
        """An INSERT referencing a block named 'TITLE*' should produce a TitleBlock."""
        def builder(doc, msp):
            # Create a block named "TITLE_BLOCK" with ATTDEF entities
            # ezdxf uses 'text' parameter for the default value of ATTDEF (not 'default')
            blk = doc.blocks.new("TITLE_BLOCK")
            blk.add_attdef("PART_NUMBER", insert=(0, 0), text="PN-001")
            blk.add_attdef("REVISION", insert=(0, -5), text="A")
            blk.add_attdef("MATERIAL", insert=(0, -10), text="STEEL")
            blk.add_attdef("SCALE", insert=(0, -15), text="1:1")
            blk.add_attdef("UNITS", insert=(0, -20), text="mm")
            # Insert the block into modelspace
            msp.add_blockref("TITLE_BLOCK", insert=(0, 0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert model.title_block is not None

    def test_insert_without_title_in_name_ignored(self) -> None:
        """An INSERT referencing a block without 'TITLE' in its name should be ignored."""
        def builder(doc, msp):
            blk = doc.blocks.new("SYMBOL_BLOCK")
            blk.add_attdef("TAG1", insert=(0, 0), text="value1")
            msp.add_blockref("SYMBOL_BLOCK", insert=(0, 0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert model.title_block is None

    def test_title_block_attrib_values_extracted(self) -> None:
        """Title block ATTRIB values should be mapped to TitleBlock fields."""
        def builder(doc, msp):
            blk = doc.blocks.new("TITLE_BLOCK")
            blk.add_attdef("PART_NUMBER", insert=(0, 0), text="PN-123")
            blk.add_attdef("REVISION", insert=(0, -5), text="B")
            blk.add_attdef("MATERIAL", insert=(0, -10), text="ALUMINUM")
            blk.add_attdef("SCALE", insert=(0, -15), text="2:1")
            blk.add_attdef("UNITS", insert=(0, -20), text="in")
            msp.add_blockref("TITLE_BLOCK", insert=(0, 0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        tb = model.title_block
        assert tb is not None
        assert tb.part_number == "PN-123"
        assert tb.revision == "B"
        assert tb.material == "ALUMINUM"
        assert tb.scale == "2:1"
        assert tb.units == "in"

    def test_title_block_case_insensitive_block_name(self) -> None:
        """Block names containing 'title' (any case) should be recognized."""
        def builder(doc, msp):
            blk = doc.blocks.new("title_block")
            blk.add_attdef("PART_NUMBER", insert=(0, 0), text="PN-456")
            msp.add_blockref("title_block", insert=(0, 0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert model.title_block is not None

    def test_title_block_missing_fields_are_none(self) -> None:
        """Missing title block fields should be None, not raise an error."""
        def builder(doc, msp):
            blk = doc.blocks.new("TITLE_BLOCK")
            # Only provide part number; other fields absent
            blk.add_attdef("PART_NUMBER", insert=(0, 0), text="PN-789")
            msp.add_blockref("TITLE_BLOCK", insert=(0, 0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        tb = model.title_block
        assert tb is not None
        assert tb.part_number == "PN-789"
        assert tb.revision is None
        assert tb.material is None
        assert tb.scale is None
        assert tb.units is None


# ---------------------------------------------------------------------------
# TEXT / MTEXT entity extraction
# ---------------------------------------------------------------------------


class TestTextExtraction:
    def test_text_entity_added_to_notes(self) -> None:
        """A TEXT entity should be added to the model's notes list."""
        def builder(doc, msp):
            msp.add_text("GENERAL TOLERANCE: ±0.1", dxfattribs={"insert": (0, 0)})

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert any("GENERAL TOLERANCE" in note for note in model.notes)

    def test_mtext_entity_added_to_notes(self) -> None:
        """An MTEXT entity should be added to the model's notes list."""
        def builder(doc, msp):
            msp.add_mtext("SURFACE FINISH: 1.6 Ra", dxfattribs={"insert": (0, 0)})

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        assert any("SURFACE FINISH" in note for note in model.notes)

    def test_empty_text_not_added_to_notes(self) -> None:
        """Empty TEXT entities should not be added to notes."""
        def builder(doc, msp):
            msp.add_text("", dxfattribs={"insert": (0, 0)})

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "test.dxf")
        # Empty text should not appear in notes
        assert all(note.strip() for note in model.notes)


# ---------------------------------------------------------------------------
# Error handling — corrupted DXF
# ---------------------------------------------------------------------------


class TestCorruptedDXF:
    def test_completely_invalid_bytes_raises_parse_error(self) -> None:
        """Completely invalid bytes should raise ParseError."""
        data = b"\x00\x01\x02\x03 this is not a DXF file at all"
        parser = DXFParser()
        with pytest.raises(ParseError) as exc_info:
            parser.parse(data, "corrupted.dxf")
        err = exc_info.value
        assert err.file_format == "DXF"

    def test_parse_error_has_dxf_format(self) -> None:
        """ParseError raised for DXF files must have file_format == 'DXF'."""
        data = b"INVALID DXF CONTENT THAT CANNOT BE RECOVERED"
        parser = DXFParser()
        with pytest.raises(ParseError) as exc_info:
            parser.parse(data, "bad.dxf")
        assert exc_info.value.file_format == "DXF"

    def test_parse_error_message_contains_filename(self) -> None:
        """ParseError message should reference the source file path."""
        data = b"NOT A DXF"
        parser = DXFParser()
        with pytest.raises(ParseError) as exc_info:
            parser.parse(data, "my_drawing.dxf")
        assert "my_drawing.dxf" in exc_info.value.message


# ---------------------------------------------------------------------------
# Tolerance string parser unit tests
# ---------------------------------------------------------------------------


class TestParseToleranceString:
    def test_position_symbol_extracted(self) -> None:
        """GDT index 10 should map to the position symbol ⊕."""
        gdt_symbol, _, _, _ = _parse_tolerance_string("{GDT;10}|0.1|A")
        assert gdt_symbol == "⊕"

    def test_flatness_symbol_extracted(self) -> None:
        """GDT index 2 should map to the flatness symbol ⏥."""
        gdt_symbol, _, _, _ = _parse_tolerance_string("{GDT;2}|0.05")
        assert gdt_symbol == "⏥"

    def test_tolerance_value_extracted(self) -> None:
        """Numeric tolerance value should be extracted from the string."""
        _, tol_value, _, _ = _parse_tolerance_string("{GDT;10}|0.25|A")
        assert tol_value == pytest.approx(0.25)

    def test_datum_references_extracted(self) -> None:
        """Datum references (single uppercase letters) should be extracted."""
        _, _, datums, _ = _parse_tolerance_string("{GDT;10}|0.1|A|B|C")
        assert datums == ["A", "B", "C"]

    def test_material_condition_mmc_extracted(self) -> None:
        """MMC material condition should be extracted."""
        _, _, _, mc = _parse_tolerance_string("{GDT;10}{MC;1}|0.1|A")
        assert mc == "MMC"

    def test_material_condition_lmc_extracted(self) -> None:
        """LMC material condition should be extracted."""
        _, _, _, mc = _parse_tolerance_string("{GDT;10}{MC;2}|0.1|A")
        assert mc == "LMC"

    def test_material_condition_rfs_extracted(self) -> None:
        """RFS material condition should be extracted."""
        _, _, _, mc = _parse_tolerance_string("{GDT;10}{MC;0}|0.1|A")
        assert mc == "RFS"

    def test_empty_string_returns_defaults(self) -> None:
        """An empty tolerance string should return empty/None defaults."""
        gdt_symbol, tol_value, datums, mc = _parse_tolerance_string("")
        assert gdt_symbol == ""
        assert tol_value is None
        assert datums == []
        assert mc is None

    def test_unknown_gdt_index_returns_fallback(self) -> None:
        """An unknown GDT index should return a fallback string."""
        gdt_symbol, _, _, _ = _parse_tolerance_string("{GDT;99}|0.1")
        assert gdt_symbol == "GDT99"


# ---------------------------------------------------------------------------
# Integration — mixed drawing with multiple entity types
# ---------------------------------------------------------------------------


class TestMixedDrawing:
    def test_mixed_drawing_extracts_all_entity_types(self) -> None:
        """A drawing with multiple entity types should extract all of them."""
        def builder(doc, msp):
            doc.header["$INSUNITS"] = 4  # mm
            # Geometry
            msp.add_line((0, 0), (100, 0))
            msp.add_circle(center=(50, 50), radius=10)
            # Dimension
            msp.add_linear_dim(base=(0, 20), p1=(0, 0), p2=(100, 0)).render()
            # Tolerance (GD&T FCF) — use new_entity() with 'content' attribute
            msp.new_entity("TOLERANCE", dxfattribs={"content": "{GDT;10}|0.1|A", "insert": (50, 30)})
            # Text note
            msp.add_text("MATERIAL: STEEL", dxfattribs={"insert": (0, -10)})
            # Title block — use text= parameter for ATTDEF default value
            blk = doc.blocks.new("TITLE_BLOCK")
            blk.add_attdef("PART_NUMBER", insert=(0, 0), text="PN-001")
            blk.add_attdef("REVISION", insert=(0, -5), text="A")
            msp.add_blockref("TITLE_BLOCK", insert=(200, 0))

        data = _make_dxf_bytes(builder=builder)
        parser = DXFParser()
        model = parser.parse(data, "mixed.dxf")

        assert model.source_format == DrawingFormat.DXF
        assert len(model.features) >= 2  # LINE + CIRCLE
        assert len(model.dimensions) >= 1
        assert len(model.feature_control_frames) >= 1
        assert len(model.notes) >= 1
        assert model.title_block is not None
        assert model.title_block.part_number == "PN-001"
        assert model.title_block.revision == "A"
