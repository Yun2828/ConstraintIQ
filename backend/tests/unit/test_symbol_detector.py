"""Unit tests for the SymbolDetector (DPSS) component.

Covers:
- Heuristic fallback detection from GeometricModel data
- enrich() merging of high-confidence detections (>= 0.8)
- enrich() discarding of low-confidence detections (< 0.5)
- enrich() tentative merging (0.5 <= confidence < 0.8) without overwriting
  existing feature_type
- WARNING Issue appended when model weights are unavailable
- detect() returns empty list when model is unavailable (no primitives in model)
"""

import pytest

from engineering_drawing_analyzer import (
    DetectedSymbol,
    SymbolDetector,
)
from engineering_drawing_analyzer.models import (
    Datum,
    Dimension,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    Issue,
    LocationReference,
    Point2D,
    Severity,
    TitleBlock,
    Tolerance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _loc(x: float = 0.0, y: float = 0.0) -> LocationReference:
    return LocationReference(
        view_name="FRONT",
        coordinates=Point2D(x, y),
        label=None,
    )


def _make_detector(threshold: float = 0.5) -> SymbolDetector:
    """Return a SymbolDetector in heuristic-only mode (no weights file)."""
    return SymbolDetector(
        model_weights_path="/nonexistent/weights.pt",
        confidence_threshold=threshold,
    )


def _minimal_model() -> GeometricModel:
    """A GeometricModel with one of each entity type."""
    feature = Feature(
        id="F1",
        feature_type="HOLE",
        dimensions=[
            Dimension(
                id="D1",
                value=10.0,
                unit="mm",
                tolerance=Tolerance(upper=0.1, lower=-0.1),
                location=_loc(1.0, 2.0),
                associated_feature_ids=["F1"],
            )
        ],
        location=_loc(1.0, 2.0),
    )
    dim = Dimension(
        id="D2",
        value=25.0,
        unit="mm",
        tolerance=None,
        location=_loc(5.0, 5.0),
    )
    fcf = FeatureControlFrame(
        id="FCF1",
        gdt_symbol="⊕",
        tolerance_value=0.05,
        datum_references=["A", "B"],
        material_condition="MMC",
        location=_loc(3.0, 3.0),
    )
    datum = Datum(
        label="A",
        feature_id="F1",
        location=_loc(0.0, 0.0),
    )
    tb = TitleBlock(
        part_number="PN-001",
        revision="A",
        material="Steel",
        scale="1:1",
        units="mm",
    )
    return GeometricModel(
        features=[feature],
        dimensions=[dim],
        datums=[datum],
        feature_control_frames=[fcf],
        title_block=tb,
    )


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestSymbolDetectorInit:
    def test_model_unavailable_when_weights_missing(self):
        detector = _make_detector()
        assert detector._model_available is False

    def test_confidence_threshold_stored(self):
        detector = SymbolDetector("/nonexistent/w.pt", confidence_threshold=0.7)
        assert detector.confidence_threshold == 0.7

    def test_default_confidence_threshold(self):
        detector = SymbolDetector("/nonexistent/w.pt")
        assert detector.confidence_threshold == 0.5


# ---------------------------------------------------------------------------
# detect() — heuristic fallback
# ---------------------------------------------------------------------------


class TestDetectHeuristic:
    def test_returns_list(self):
        detector = _make_detector()
        model = _minimal_model()
        result = detector.detect(model)
        assert isinstance(result, list)

    def test_detects_feature(self):
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        feature_syms = [s for s in symbols if s.symbol_type == "FEATURE"]
        assert len(feature_syms) == 1
        assert "F1" in feature_syms[0].primitive_ids

    def test_detects_dimension(self):
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        dim_syms = [s for s in symbols if s.symbol_type == "DIMENSION"]
        # model has one top-level dimension (D2); D1 is inside the feature
        assert len(dim_syms) == 1
        assert "D2" in dim_syms[0].primitive_ids

    def test_detects_gdt_fcf(self):
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        fcf_syms = [s for s in symbols if s.symbol_type == "GDT_FCF"]
        assert len(fcf_syms) == 1
        assert "FCF1" in fcf_syms[0].primitive_ids

    def test_detects_datum(self):
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        datum_syms = [s for s in symbols if s.symbol_type == "DATUM"]
        assert len(datum_syms) == 1
        assert datum_syms[0].attributes["label"] == "A"

    def test_detects_title_block(self):
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        tb_syms = [s for s in symbols if s.symbol_type == "TITLE_BLOCK"]
        assert len(tb_syms) == 1
        assert tb_syms[0].attributes["part_number"] == "PN-001"

    def test_all_confidences_above_threshold(self):
        detector = _make_detector(threshold=0.5)
        model = _minimal_model()
        symbols = detector.detect(model)
        for sym in symbols:
            assert sym.confidence >= 0.5

    def test_high_threshold_filters_out_symbols(self):
        """With threshold=0.99 nothing should pass."""
        detector = _make_detector(threshold=0.99)
        model = _minimal_model()
        symbols = detector.detect(model)
        assert symbols == []

    def test_empty_model_returns_empty_list(self):
        detector = _make_detector()
        model = GeometricModel()
        symbols = detector.detect(model)
        assert symbols == []

    def test_feature_with_empty_type_gets_lower_confidence(self):
        """A Feature with an empty feature_type should get confidence < 0.5."""
        detector = _make_detector(threshold=0.5)
        model = GeometricModel(
            features=[Feature(id="F_EMPTY", feature_type="")]
        )
        symbols = detector.detect(model)
        feature_syms = [s for s in symbols if s.symbol_type == "FEATURE"]
        # confidence for empty feature_type is 0.4, below threshold 0.5
        assert len(feature_syms) == 0

    def test_raster_image_none_uses_heuristic(self):
        """Passing raster_image=None should still return heuristic results."""
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model, raster_image=None)
        assert len(symbols) > 0

    def test_bounding_box_type(self):
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        for sym in symbols:
            assert isinstance(sym.bounding_box, tuple)
            assert len(sym.bounding_box) == 2
            assert isinstance(sym.bounding_box[0], Point2D)
            assert isinstance(sym.bounding_box[1], Point2D)


# ---------------------------------------------------------------------------
# enrich() — confidence thresholding and merging
# ---------------------------------------------------------------------------


class TestEnrich:
    def _make_feature(self, fid: str = "F1", ftype: str = "HOLE") -> Feature:
        return Feature(id=fid, feature_type=ftype, location=_loc())

    def test_high_confidence_updates_ml_fields(self):
        """confidence >= 0.8 → ml_confidence and ml_symbol_type are set."""
        detector = _make_detector()
        feature = self._make_feature()
        model = GeometricModel(features=[feature])
        symbol = DetectedSymbol(
            symbol_type="FEATURE",
            confidence=0.90,
            primitive_ids=["F1"],
            attributes={"feature_type": "SLOT"},
        )
        enriched_model, issues = detector.enrich(model, [symbol])
        f = enriched_model.features[0]
        assert f.ml_confidence == 0.90
        assert f.ml_symbol_type == "FEATURE"

    def test_high_confidence_overwrites_feature_type(self):
        """confidence >= 0.8 → feature_type is overwritten with ML result."""
        detector = _make_detector()
        feature = self._make_feature(ftype="HOLE")
        model = GeometricModel(features=[feature])
        symbol = DetectedSymbol(
            symbol_type="FEATURE",
            confidence=0.85,
            primitive_ids=["F1"],
            attributes={"feature_type": "SLOT"},
        )
        enriched_model, _ = detector.enrich(model, [symbol])
        assert enriched_model.features[0].feature_type == "SLOT"

    def test_tentative_confidence_sets_ml_confidence(self):
        """0.5 <= confidence < 0.8 → ml_confidence is set."""
        detector = _make_detector()
        feature = self._make_feature(ftype="HOLE")
        model = GeometricModel(features=[feature])
        symbol = DetectedSymbol(
            symbol_type="FEATURE",
            confidence=0.65,
            primitive_ids=["F1"],
            attributes={"feature_type": "SLOT"},
        )
        enriched_model, _ = detector.enrich(model, [symbol])
        f = enriched_model.features[0]
        assert f.ml_confidence == 0.65

    def test_tentative_confidence_does_not_overwrite_existing_feature_type(self):
        """0.5 <= confidence < 0.8 → existing feature_type is preserved."""
        detector = _make_detector()
        feature = self._make_feature(ftype="HOLE")
        model = GeometricModel(features=[feature])
        symbol = DetectedSymbol(
            symbol_type="FEATURE",
            confidence=0.65,
            primitive_ids=["F1"],
            attributes={"feature_type": "SLOT"},
        )
        enriched_model, _ = detector.enrich(model, [symbol])
        # Heuristic parser value (HOLE) must not be overwritten.
        assert enriched_model.features[0].feature_type == "HOLE"

    def test_tentative_confidence_sets_feature_type_when_empty(self):
        """0.5 <= confidence < 0.8 → feature_type is set if it was empty."""
        detector = _make_detector()
        feature = self._make_feature(ftype="")
        model = GeometricModel(features=[feature])
        symbol = DetectedSymbol(
            symbol_type="FEATURE",
            confidence=0.65,
            primitive_ids=["F1"],
            attributes={"feature_type": "SLOT"},
        )
        enriched_model, _ = detector.enrich(model, [symbol])
        assert enriched_model.features[0].feature_type == "SLOT"

    def test_low_confidence_discarded(self):
        """confidence < 0.5 → feature is not modified at all."""
        detector = _make_detector()
        feature = self._make_feature(ftype="HOLE")
        model = GeometricModel(features=[feature])
        symbol = DetectedSymbol(
            symbol_type="FEATURE",
            confidence=0.30,
            primitive_ids=["F1"],
            attributes={"feature_type": "SLOT"},
        )
        enriched_model, _ = detector.enrich(model, [symbol])
        f = enriched_model.features[0]
        assert f.feature_type == "HOLE"
        assert f.ml_confidence is None
        assert f.ml_symbol_type is None

    def test_unknown_primitive_id_is_ignored(self):
        """A symbol referencing a non-existent feature ID should not crash."""
        detector = _make_detector()
        model = GeometricModel(features=[self._make_feature("F1")])
        symbol = DetectedSymbol(
            symbol_type="FEATURE",
            confidence=0.90,
            primitive_ids=["DOES_NOT_EXIST"],
            attributes={"feature_type": "SLOT"},
        )
        enriched_model, _ = detector.enrich(model, [symbol])
        # F1 should be untouched
        assert enriched_model.features[0].ml_confidence is None

    def test_returns_tuple_of_model_and_issues(self):
        detector = _make_detector()
        model = GeometricModel()
        result = detector.enrich(model, [])
        assert isinstance(result, tuple)
        assert len(result) == 2
        enriched_model, issues = result
        assert isinstance(enriched_model, GeometricModel)
        assert isinstance(issues, list)

    def test_model_unavailable_appends_warning_issue(self):
        """When model weights are unavailable, a WARNING Issue is appended."""
        detector = _make_detector()
        assert detector._model_available is False
        model = GeometricModel()
        _, issues = detector.enrich(model, [])
        assert len(issues) == 1
        issue = issues[0]
        assert isinstance(issue, Issue)
        assert issue.severity == Severity.WARNING
        assert issue.rule_id == "SYMBOL_DETECTOR"
        assert issue.issue_type == "ML_UNAVAILABLE"

    def test_model_unavailable_warning_message_content(self):
        """The WARNING issue description should mention ML unavailability."""
        detector = _make_detector()
        _, issues = detector.enrich(GeometricModel(), [])
        assert "ML-assisted symbol detection was unavailable" in issues[0].description

    def test_multiple_symbols_all_processed(self):
        """Multiple symbols should all be processed in one enrich() call."""
        detector = _make_detector()
        f1 = self._make_feature("F1", "HOLE")
        f2 = self._make_feature("F2", "SLOT")
        model = GeometricModel(features=[f1, f2])
        symbols = [
            DetectedSymbol(
                symbol_type="FEATURE",
                confidence=0.90,
                primitive_ids=["F1"],
                attributes={"feature_type": "SURFACE"},
            ),
            DetectedSymbol(
                symbol_type="FEATURE",
                confidence=0.85,
                primitive_ids=["F2"],
                attributes={"feature_type": "EDGE"},
            ),
        ]
        enriched_model, _ = detector.enrich(model, symbols)
        assert enriched_model.features[0].feature_type == "SURFACE"
        assert enriched_model.features[1].feature_type == "EDGE"

    def test_non_feature_symbols_do_not_crash(self):
        """DIMENSION / GDT_FCF / DATUM / TITLE_BLOCK symbols should not crash."""
        detector = _make_detector()
        model = _minimal_model()
        symbols = [
            DetectedSymbol(
                symbol_type="DIMENSION",
                confidence=0.80,
                primitive_ids=["D2"],
                attributes={"value": 25.0},
            ),
            DetectedSymbol(
                symbol_type="GDT_FCF",
                confidence=0.75,
                primitive_ids=["FCF1"],
                attributes={"gdt_symbol": "⊕"},
            ),
            DetectedSymbol(
                symbol_type="TITLE_BLOCK",
                confidence=0.90,
                primitive_ids=[],
                attributes={"part_number": "PN-001"},
            ),
        ]
        enriched_model, _ = detector.enrich(model, symbols)
        # No crash; model is returned unchanged for non-FEATURE symbols
        assert enriched_model is model


# ---------------------------------------------------------------------------
# Integration: detect() → enrich() round-trip
# ---------------------------------------------------------------------------


class TestDetectEnrichRoundTrip:
    def test_heuristic_detect_then_enrich_sets_ml_confidence(self):
        """Running detect() then enrich() should set ml_confidence on features."""
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        enriched_model, issues = detector.enrich(model, symbols)
        # The feature F1 should have ml_confidence set (heuristic confidence >= 0.5)
        f1 = next(f for f in enriched_model.features if f.id == "F1")
        assert f1.ml_confidence is not None
        assert 0.5 <= f1.ml_confidence <= 1.0

    def test_warning_issue_present_after_enrich(self):
        """enrich() always appends a WARNING when model is unavailable."""
        detector = _make_detector()
        model = _minimal_model()
        symbols = detector.detect(model)
        _, issues = detector.enrich(model, symbols)
        warning_issues = [i for i in issues if i.severity == Severity.WARNING]
        assert len(warning_issues) >= 1
