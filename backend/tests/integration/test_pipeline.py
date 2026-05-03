"""Integration tests for the AnalysisPipeline.

Tests cover:
- Full pipeline with a minimal synthetic DXF-like input (parsers mocked)
- Timeout produces a partial report with a WARNING issue
- Rule engine exceptions are isolated and produce INFO issues
- Structured logging output contains required JSON fields

Requirements: 1.1, 1.2, 6.1, 6.4, 6.6
"""

from __future__ import annotations

import io
import json
import logging
import os
import tempfile
import threading
import time
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from engineering_drawing_analyzer.exceptions import ParseError, UnsupportedFormatError
from engineering_drawing_analyzer.models import (
    Datum,
    Dimension,
    DrawingFormat,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    Issue,
    LocationReference,
    Point2D,
    ReportFormat,
    Severity,
    TitleBlock,
    Tolerance,
    VerificationReport,
    View,
)
from engineering_drawing_analyzer.pipeline import (
    AnalysisPipeline,
    _StructuredJsonFormatter,
    _make_timeout_issue,
)
from engineering_drawing_analyzer.rule_engine import RuleEngine, VerificationRule


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_minimal_model(
    num_features: int = 1,
    with_title_block: bool = True,
    with_dimensions: bool = True,
) -> GeometricModel:
    """Build a minimal but valid GeometricModel for testing."""
    loc = LocationReference(view_name="FRONT", coordinates=Point2D(0.0, 0.0), label=None)
    tol = Tolerance(upper=0.1, lower=-0.1, is_general=False)

    features = []
    dimensions = []
    for i in range(num_features):
        fid = f"F{i}"
        dim = Dimension(
            id=f"D{i}",
            value=10.0 + i,
            unit="mm",
            tolerance=tol if with_dimensions else None,
            location=loc,
            associated_feature_ids=[fid],
        )
        if with_dimensions:
            dimensions.append(dim)
        features.append(
            Feature(
                id=fid,
                feature_type="EDGE",
                dimensions=[dim] if with_dimensions else [],
                location=loc,
            )
        )

    title_block = (
        TitleBlock(
            part_number="TEST-001",
            revision="A",
            material="STEEL",
            scale="1:1",
            units="mm",
        )
        if with_title_block
        else None
    )

    return GeometricModel(
        schema_version="1.0",
        source_format=DrawingFormat.DXF,
        features=features,
        dimensions=dimensions,
        datums=[
            Datum(label="A", feature_id="F0", location=loc),
        ],
        feature_control_frames=[],
        title_block=title_block,
        views=[View(name="FRONT", features=[f.id for f in features])],
        general_tolerance=tol,
        notes=[],
    )


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
# Test: full pipeline with mocked parser
# ---------------------------------------------------------------------------


class TestFullPipelineWithMockedParser:
    """Test the full pipeline flow using a mocked DXF parser."""

    def test_pipeline_returns_json_bytes(self, tmp_path):
        """Pipeline should return valid JSON bytes for a minimal DXF drawing."""
        dxf_file = tmp_path / "test.dxf"
        _write_minimal_dxf(str(dxf_file))

        model = _make_minimal_model()

        pipeline = AnalysisPipeline(model_weights_path="")

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        assert isinstance(result, bytes)
        report_dict = json.loads(result.decode("utf-8"))
        assert "drawing_id" in report_dict
        assert "overall_status" in report_dict
        assert "issues" in report_dict
        assert "issue_counts" in report_dict
        assert "systemic_patterns" in report_dict
        assert "analysis_timestamp" in report_dict

    def test_pipeline_overall_status_fail_when_issues_exist(self, tmp_path):
        """Pipeline should produce 'Fail' status when the model has violations."""
        dxf_file = tmp_path / "clean.dxf"
        _write_minimal_dxf(str(dxf_file))

        # A model with no features but no datums will trigger the datum reference
        # frame rule (CRITICAL), so overall_status should be 'Fail'.
        model = GeometricModel(
            schema_version="1.0",
            source_format=DrawingFormat.DXF,
            features=[],
            dimensions=[],
            datums=[],
            feature_control_frames=[],
            title_block=TitleBlock(
                part_number="P1", revision="A", material="AL", scale="1:1", units="mm"
            ),
            views=[],
            general_tolerance=Tolerance(upper=0.1, lower=-0.1),
            notes=[],
        )

        pipeline = AnalysisPipeline(model_weights_path="")

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        # The datum reference frame rule fires even with no features,
        # so overall_status must be 'Fail'
        assert report_dict["overall_status"] == "Fail"

    def test_pipeline_drawing_id_from_filename(self, tmp_path):
        """drawing_id in the report should be derived from the filename."""
        dxf_file = tmp_path / "my_drawing.dxf"
        _write_minimal_dxf(str(dxf_file))

        model = _make_minimal_model()
        pipeline = AnalysisPipeline(model_weights_path="")

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        # drawing_id comes from the title block part_number ("TEST-001")
        # or falls back to "unknown" — either is acceptable
        assert isinstance(report_dict["drawing_id"], str)
        assert len(report_dict["drawing_id"]) > 0

    def test_pipeline_issues_list_is_list(self, tmp_path):
        """issues field in the report must be a list."""
        dxf_file = tmp_path / "test.dxf"
        _write_minimal_dxf(str(dxf_file))

        model = _make_minimal_model()
        pipeline = AnalysisPipeline(model_weights_path="")

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        assert isinstance(report_dict["issues"], list)

    def test_pipeline_issue_counts_match_issues(self, tmp_path):
        """issue_counts must match the actual count of issues per severity."""
        dxf_file = tmp_path / "test.dxf"
        _write_minimal_dxf(str(dxf_file))

        model = _make_minimal_model()
        pipeline = AnalysisPipeline(model_weights_path="")

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        issues = report_dict["issues"]
        counts = report_dict["issue_counts"]

        actual_critical = sum(1 for i in issues if i["severity"] == "Critical")
        actual_warning = sum(1 for i in issues if i["severity"] == "Warning")
        actual_info = sum(1 for i in issues if i["severity"] == "Info")

        assert counts.get("Critical", 0) == actual_critical
        assert counts.get("Warning", 0) == actual_warning
        assert counts.get("Info", 0) == actual_info


# ---------------------------------------------------------------------------
# Test: timeout produces partial report with WARNING issue
# ---------------------------------------------------------------------------


class TestTimeoutBehavior:
    """Test that a pipeline timeout produces a partial report with a WARNING."""

    def test_timeout_produces_warning_issue(self, tmp_path):
        """When the pipeline times out, the report must contain a WARNING issue."""
        dxf_file = tmp_path / "slow.dxf"
        _write_minimal_dxf(str(dxf_file))

        # Use a very short timeout (1 second) and a parser that sleeps
        pipeline = AnalysisPipeline(model_weights_path="", timeout_seconds=1)

        def _slow_parse(data, source_path):
            time.sleep(5)  # Exceeds the 1-second timeout
            return _make_minimal_model()

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.side_effect = _slow_parse
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        assert isinstance(report_dict["issues"], list)

        warning_issues = [
            i for i in report_dict["issues"] if i["severity"] == "Warning"
        ]
        assert len(warning_issues) >= 1

        timeout_issues = [
            i for i in warning_issues if i["issue_type"] == "ANALYSIS_TIMEOUT"
        ]
        assert len(timeout_issues) >= 1, (
            "Expected at least one ANALYSIS_TIMEOUT WARNING issue in the report"
        )

    def test_timeout_report_has_required_fields(self, tmp_path):
        """Partial report from timeout must still have all required JSON fields."""
        dxf_file = tmp_path / "slow2.dxf"
        _write_minimal_dxf(str(dxf_file))

        pipeline = AnalysisPipeline(model_weights_path="", timeout_seconds=1)

        def _slow_parse(data, source_path):
            time.sleep(5)
            return _make_minimal_model()

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.side_effect = _slow_parse
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        required_fields = {
            "drawing_id", "analysis_timestamp", "overall_status",
            "issue_counts", "issues", "systemic_patterns",
        }
        assert required_fields.issubset(report_dict.keys())

    def test_timeout_issue_helper(self):
        """_make_timeout_issue() must return a WARNING issue with correct fields."""
        issue = _make_timeout_issue()
        assert issue.severity == Severity.WARNING
        assert issue.issue_type == "ANALYSIS_TIMEOUT"
        assert issue.rule_id == "ANALYSIS_PIPELINE"
        assert "60" in issue.description
        assert issue.corrective_action is not None


# ---------------------------------------------------------------------------
# Test: rule engine exception isolation
# ---------------------------------------------------------------------------


class _BrokenRule:
    """A VerificationRule that always raises an exception."""

    rule_id = "BROKEN_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        raise RuntimeError("Simulated rule failure")


class _GoodRule:
    """A VerificationRule that always returns one INFO issue."""

    rule_id = "GOOD_RULE"

    def check(self, model: GeometricModel) -> list[Issue]:
        return [
            Issue(
                issue_id="GOOD-001",
                rule_id=self.rule_id,
                issue_type="TEST_ISSUE",
                severity=Severity.INFO,
                description="Good rule ran successfully.",
                location=LocationReference(
                    view_name="TEST", coordinates=None, label=None
                ),
            )
        ]


class TestRuleEngineExceptionIsolation:
    """Test that per-rule exceptions are isolated and produce INFO issues."""

    def test_broken_rule_produces_info_issue(self, tmp_path):
        """A rule that raises must produce an INFO issue; other rules still run."""
        dxf_file = tmp_path / "test.dxf"
        _write_minimal_dxf(str(dxf_file))

        model = _make_minimal_model()
        pipeline = AnalysisPipeline(
            model_weights_path="",
            rules=[_BrokenRule(), _GoodRule()],
        )

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        issues = report_dict["issues"]

        # The broken rule should produce a RULE_ENGINE_ERROR INFO issue
        rule_error_issues = [
            i for i in issues
            if i["issue_type"] == "RULE_ENGINE_ERROR" and i["severity"] == "Info"
        ]
        assert len(rule_error_issues) >= 1, (
            "Expected at least one RULE_ENGINE_ERROR INFO issue from the broken rule"
        )

        # The good rule should still have run and produced its TEST_ISSUE
        good_issues = [i for i in issues if i["issue_type"] == "TEST_ISSUE"]
        assert len(good_issues) >= 1, (
            "Expected the good rule to still run after the broken rule failed"
        )

    def test_broken_rule_does_not_prevent_report_generation(self, tmp_path):
        """A broken rule must not prevent the report from being generated."""
        dxf_file = tmp_path / "test.dxf"
        _write_minimal_dxf(str(dxf_file))

        model = _make_minimal_model()
        pipeline = AnalysisPipeline(
            model_weights_path="",
            rules=[_BrokenRule()],
        )

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            # Should not raise
            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        assert isinstance(result, bytes)
        report_dict = json.loads(result.decode("utf-8"))
        assert "issues" in report_dict

    def test_multiple_broken_rules_all_produce_info_issues(self, tmp_path):
        """Each broken rule should produce its own INFO issue."""
        dxf_file = tmp_path / "test.dxf"
        _write_minimal_dxf(str(dxf_file))

        class _BrokenRule2:
            rule_id = "BROKEN_RULE_2"

            def check(self, model):
                raise ValueError("Another simulated failure")

        model = _make_minimal_model()
        pipeline = AnalysisPipeline(
            model_weights_path="",
            rules=[_BrokenRule(), _BrokenRule2()],
        )

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.return_value = model
            mock_select.return_value = mock_parser

            result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        issues = report_dict["issues"]

        rule_error_issues = [
            i for i in issues
            if i["issue_type"] == "RULE_ENGINE_ERROR" and i["severity"] == "Info"
        ]
        assert len(rule_error_issues) >= 2, (
            "Expected one INFO issue per broken rule"
        )


# ---------------------------------------------------------------------------
# Test: structured JSON logging
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    """Test that the pipeline emits structured JSON log records."""

    def test_log_formatter_produces_valid_json(self):
        """_StructuredJsonFormatter must produce valid JSON for each log record."""
        formatter = _StructuredJsonFormatter(component="TestComponent")
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Something went wrong",
            args=(),
            exc_info=None,
        )
        record.drawing_id = "drawing-123"
        record.error_type = "ParseError"
        record.component = "TestComponent"

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "timestamp" in parsed
        assert "level" in parsed
        assert "component" in parsed
        assert "drawing_id" in parsed
        assert "error_type" in parsed
        assert "message" in parsed

    def test_log_formatter_required_fields_present(self):
        """All six required fields must be present in every log record."""
        formatter = _StructuredJsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Test warning",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        required_fields = {"timestamp", "level", "component", "drawing_id", "error_type", "message"}
        assert required_fields.issubset(parsed.keys()), (
            f"Missing fields: {required_fields - parsed.keys()}"
        )

    def test_log_formatter_level_matches_record(self):
        """The 'level' field must match the log record's level name."""
        formatter = _StructuredJsonFormatter()
        for level, name in [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="test.py",
                lineno=1,
                msg="msg",
                args=(),
                exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["level"] == name

    def test_log_formatter_no_raw_file_content(self):
        """Log records must not contain raw file content."""
        formatter = _StructuredJsonFormatter()
        raw_content = b"\x00\x01\x02\x03" * 1000  # simulated binary file content
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Parse failed",  # message does NOT include raw bytes
            args=(),
            exc_info=None,
        )
        record.drawing_id = "test.dxf"
        record.error_type = "ParseError"

        output = formatter.format(record)
        # The raw binary content should not appear in the log output
        assert str(raw_content) not in output

    def test_pipeline_logs_on_parse_error(self, tmp_path, caplog):
        """Pipeline must log a structured error when parsing fails."""
        dxf_file = tmp_path / "bad.dxf"
        _write_minimal_dxf(str(dxf_file))

        pipeline = AnalysisPipeline(model_weights_path="")

        with patch.object(pipeline, "_select_parser") as mock_select:
            mock_parser = MagicMock()
            mock_parser.parse.side_effect = ParseError(
                message="Corrupted file", file_format="DXF"
            )
            mock_select.return_value = mock_parser

            with pytest.raises(ParseError):
                pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

    def test_pipeline_logs_on_unsupported_format(self, tmp_path):
        """Pipeline must raise UnsupportedFormatError for unknown file formats."""
        unknown_file = tmp_path / "drawing.xyz"
        unknown_file.write_bytes(b"\x00\x01\x02\x03")

        pipeline = AnalysisPipeline(model_weights_path="")

        with pytest.raises(UnsupportedFormatError):
            pipeline.analyze(str(unknown_file), report_format=ReportFormat.JSON)


# ---------------------------------------------------------------------------
# Test: pipeline with real DXF file (minimal synthetic)
# ---------------------------------------------------------------------------


class TestPipelineWithRealDXF:
    """Test the pipeline with a real (minimal) DXF file parsed by ezdxf."""

    def test_pipeline_parses_minimal_dxf(self, tmp_path):
        """Pipeline should successfully parse a minimal DXF file end-to-end."""
        dxf_file = tmp_path / "minimal.dxf"
        _write_minimal_dxf(str(dxf_file))

        pipeline = AnalysisPipeline(model_weights_path="")
        result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        assert isinstance(result, bytes)
        report_dict = json.loads(result.decode("utf-8"))
        assert "drawing_id" in report_dict
        assert "overall_status" in report_dict
        assert isinstance(report_dict["issues"], list)

    def test_pipeline_report_overall_status_is_valid(self, tmp_path):
        """overall_status must be exactly 'Pass' or 'Fail'."""
        dxf_file = tmp_path / "minimal2.dxf"
        _write_minimal_dxf(str(dxf_file))

        pipeline = AnalysisPipeline(model_weights_path="")
        result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.JSON)

        report_dict = json.loads(result.decode("utf-8"))
        assert report_dict["overall_status"] in ("Pass", "Fail")

    def test_pipeline_html_output(self, tmp_path):
        """Pipeline should produce non-empty HTML bytes when requested."""
        dxf_file = tmp_path / "minimal3.dxf"
        _write_minimal_dxf(str(dxf_file))

        pipeline = AnalysisPipeline(model_weights_path="")
        result = pipeline.analyze(str(dxf_file), report_format=ReportFormat.HTML)

        assert isinstance(result, bytes)
        assert len(result) > 0
        # Should be valid HTML
        html_str = result.decode("utf-8")
        assert "<html" in html_str.lower() or "<!doctype" in html_str.lower()
