"""Performance benchmark test for the 60-second SLA.

Generates a synthetic GeometricModel with exactly 500 features and runs the
full pipeline (excluding ML inference) through AnalysisPipeline, asserting
completion within 60 seconds.

Requirements: 6.6
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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
    ReportFormat,
    TitleBlock,
    Tolerance,
    View,
)
from engineering_drawing_analyzer.pipeline import AnalysisPipeline

# ---------------------------------------------------------------------------
# SLA constant (must match pipeline.py)
# ---------------------------------------------------------------------------

_SLA_SECONDS = 60.0


# ---------------------------------------------------------------------------
# Synthetic model factory
# ---------------------------------------------------------------------------


def _build_500_feature_model() -> GeometricModel:
    """Build a synthetic GeometricModel with exactly 500 features.

    Each feature has:
    - One size dimension with a tolerance
    - One position dimension referencing datum "A"
    - A location reference

    The model also includes a valid title block, a datum reference frame,
    and a general tolerance so that the rule engine has realistic data to
    process without generating excessive noise.
    """
    num_features = 500

    loc = LocationReference(
        view_name="FRONT",
        coordinates=Point2D(0.0, 0.0),
        label=None,
    )
    tol = Tolerance(upper=0.05, lower=-0.05, is_general=False)
    general_tol = Tolerance(upper=0.1, lower=-0.1, is_general=True)

    features: list[Feature] = []
    dimensions: list[Dimension] = []
    datums: list[Datum] = []

    # Primary datum
    datum_a_feature_id = "F0"
    datums.append(
        Datum(
            label="A",
            feature_id=datum_a_feature_id,
            location=loc,
        )
    )

    for i in range(num_features):
        fid = f"F{i}"
        # Size dimension
        size_dim = Dimension(
            id=f"D_SIZE_{i}",
            value=10.0 + (i % 100) * 0.1,
            unit="mm",
            tolerance=tol,
            location=LocationReference(
                view_name="FRONT",
                coordinates=Point2D(float(i % 50), float(i // 50)),
                label=f"DIM_{i}",
            ),
            associated_feature_ids=[fid],
        )
        # Position dimension (relative to datum A)
        pos_dim = Dimension(
            id=f"D_POS_{i}",
            value=float(i % 200),
            unit="mm",
            tolerance=tol,
            location=LocationReference(
                view_name="FRONT",
                coordinates=Point2D(float(i % 50) + 0.5, float(i // 50) + 0.5),
                label=f"POS_{i}",
            ),
            associated_feature_ids=[fid, datum_a_feature_id],
        )
        dimensions.extend([size_dim, pos_dim])

        features.append(
            Feature(
                id=fid,
                feature_type="EDGE",
                dimensions=[size_dim, pos_dim],
                feature_control_frames=[],
                location=LocationReference(
                    view_name="FRONT",
                    coordinates=Point2D(float(i % 50), float(i // 50)),
                    label=fid,
                ),
                is_angular=False,
                is_threaded=False,
                is_blind_hole=False,
            )
        )

    title_block = TitleBlock(
        part_number="PERF-TEST-500",
        revision="A",
        material="STEEL",
        scale="1:1",
        units="mm",
    )

    views = [
        View(
            name="FRONT",
            features=[f.id for f in features],
        )
    ]

    return GeometricModel(
        schema_version="1.0",
        source_format=DrawingFormat.DXF,
        features=features,
        dimensions=dimensions,
        datums=datums,
        feature_control_frames=[],
        title_block=title_block,
        views=views,
        general_tolerance=general_tol,
        notes=[],
    )


# ---------------------------------------------------------------------------
# Helper: write a minimal DXF stub so IngestionService is satisfied
# ---------------------------------------------------------------------------


def _write_minimal_dxf(path: str) -> None:
    """Write a minimal valid DXF file to *path*."""
    content = (
        "0\nSECTION\n2\nHEADER\n0\nENDSEC\n"
        "0\nSECTION\n2\nENTITIES\n0\nENDSEC\n"
        "0\nEOF\n"
    )
    with open(path, "w") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# Benchmark test
# ---------------------------------------------------------------------------


def test_pipeline_500_features_within_60s(benchmark, tmp_path):
    """Benchmark: full pipeline (no ML) with 500 features must complete in ≤60 s.

    The SymbolDetector is mocked to exclude ML inference time, isolating the
    rule-engine and report-generation performance as required by Requirement 6.6.

    **Validates: Requirements 6.6**
    """
    dxf_file = tmp_path / "perf_test.dxf"
    _write_minimal_dxf(str(dxf_file))

    model = _build_500_feature_model()
    assert len(model.features) == 500, (
        f"Expected exactly 500 features, got {len(model.features)}"
    )

    pipeline = AnalysisPipeline(model_weights_path="")

    def _run_pipeline():
        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            # Also mock symbol detector to exclude ML inference
            with patch.object(pipeline._symbol_detector, "detect", return_value=[]):
                with patch.object(
                    pipeline._symbol_detector, "enrich", return_value=(model, [])
                ):
                    return pipeline.analyze(
                        str(dxf_file), report_format=ReportFormat.JSON
                    )

    result = benchmark(_run_pipeline)

    # Verify the result is a valid JSON report
    assert isinstance(result, bytes)
    report_dict = json.loads(result.decode("utf-8"))
    assert "drawing_id" in report_dict
    assert "overall_status" in report_dict
    assert isinstance(report_dict["issues"], list)

    # Assert the benchmark mean time is within the 60-second SLA
    # pytest-benchmark stores stats in benchmark.stats after the run
    mean_seconds = benchmark.stats["mean"]
    assert mean_seconds <= _SLA_SECONDS, (
        f"Pipeline mean execution time {mean_seconds:.3f}s exceeds "
        f"the {_SLA_SECONDS}s SLA for drawings with 500 features "
        f"(Requirement 6.6)."
    )
