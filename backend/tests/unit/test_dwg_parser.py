"""Unit tests for the DWG Parser.

Tests:
- Successful ODA conversion delegates correctly to DXFParser
- ODA converter failure (non-zero exit code) raises ParseError with exit code
- ODA converter not found raises ParseError
- ODA converter timeout raises ParseError
- Successful conversion sets source_format to DWG
- No DXF output produced raises ParseError

Requirements: 1.2, 1.3
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import ezdxf
import pytest

from engineering_drawing_analyzer.exceptions import ParseError
from engineering_drawing_analyzer.models import DrawingFormat, GeometricModel
from engineering_drawing_analyzer.parsers.dwg_parser import DWGParser
from engineering_drawing_analyzer.parsers.dxf_parser import DXFParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_minimal_dxf_bytes() -> bytes:
    """Create minimal valid DXF bytes for use as mock converter output."""
    doc = ezdxf.new("R2010")
    # ezdxf.write() requires a text stream; encode to bytes afterwards
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")


def _make_fake_dwg_bytes() -> bytes:
    """Return fake DWG bytes (content doesn't matter — ODA converter is mocked)."""
    return b"AC1015\x00\x00\x00\x00fake dwg content"


# ---------------------------------------------------------------------------
# Successful conversion
# ---------------------------------------------------------------------------


class TestDWGParserSuccess:
    def test_successful_conversion_returns_geometric_model(self) -> None:
        """A successful ODA conversion should return a GeometricModel."""
        dxf_bytes = _make_minimal_dxf_bytes()

        def fake_run(cmd, capture_output, timeout):
            # Write a DXF file to the output directory (second arg in cmd)
            output_dir = Path(cmd[2])
            (output_dir / "drawing.dxf").write_bytes(dxf_bytes)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            model = parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert isinstance(model, GeometricModel)

    def test_successful_conversion_sets_source_format_to_dwg(self) -> None:
        """After successful conversion, source_format must be DrawingFormat.DWG."""
        dxf_bytes = _make_minimal_dxf_bytes()

        def fake_run(cmd, capture_output, timeout):
            output_dir = Path(cmd[2])
            (output_dir / "drawing.dxf").write_bytes(dxf_bytes)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            model = parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert model.source_format == DrawingFormat.DWG

    def test_successful_conversion_delegates_to_dxf_parser(self) -> None:
        """DWGParser should delegate to DXFParser after successful conversion."""
        dxf_bytes = _make_minimal_dxf_bytes()
        mock_dxf_parser = MagicMock(spec=DXFParser)
        expected_model = GeometricModel(source_format=DrawingFormat.DWG)
        mock_dxf_parser.parse.return_value = expected_model

        def fake_run(cmd, capture_output, timeout):
            output_dir = Path(cmd[2])
            (output_dir / "drawing.dxf").write_bytes(dxf_bytes)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(
                oda_converter_path="ODAFileConverter",
                dxf_parser=mock_dxf_parser,
            )
            model = parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        # DXFParser.parse() must have been called with the DXF bytes
        mock_dxf_parser.parse.assert_called_once()
        call_args = mock_dxf_parser.parse.call_args
        assert call_args[0][0] == dxf_bytes  # first positional arg is the DXF bytes

    def test_successful_conversion_passes_source_path_to_dxf_parser(self) -> None:
        """DWGParser should pass the original source_path to DXFParser."""
        dxf_bytes = _make_minimal_dxf_bytes()
        mock_dxf_parser = MagicMock(spec=DXFParser)
        mock_dxf_parser.parse.return_value = GeometricModel(
            source_format=DrawingFormat.DWG
        )

        def fake_run(cmd, capture_output, timeout):
            output_dir = Path(cmd[2])
            (output_dir / "drawing.dxf").write_bytes(dxf_bytes)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        source_path = "path/to/my_drawing.dwg"
        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(
                oda_converter_path="ODAFileConverter",
                dxf_parser=mock_dxf_parser,
            )
            parser.parse(_make_fake_dwg_bytes(), source_path)

        call_args = mock_dxf_parser.parse.call_args
        assert call_args[0][1] == source_path  # second positional arg is source_path

    def test_dwg_file_written_to_input_dir(self) -> None:
        """The DWG bytes should be written to the temp input directory."""
        dxf_bytes = _make_minimal_dxf_bytes()
        captured_dwg_data: list[bytes] = []
        captured_suffixes: list[str] = []

        def fake_run(cmd, capture_output, timeout):
            input_dir = Path(cmd[1])
            # Capture file data while the temp dir still exists
            files = list(input_dir.iterdir())
            for f in files:
                captured_suffixes.append(f.suffix.lower())
                captured_dwg_data.append(f.read_bytes())
            output_dir = Path(cmd[2])
            (output_dir / "drawing.dxf").write_bytes(dxf_bytes)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        dwg_data = _make_fake_dwg_bytes()
        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            parser.parse(dwg_data, "drawing.dwg")

        assert len(captured_dwg_data) == 1
        assert captured_suffixes[0] == ".dwg"
        assert captured_dwg_data[0] == dwg_data

    def test_oda_converter_called_with_correct_arguments(self) -> None:
        """ODA File Converter should be called with the expected CLI arguments."""
        dxf_bytes = _make_minimal_dxf_bytes()
        captured_cmd: list[list[str]] = []

        def fake_run(cmd, capture_output, timeout):
            captured_cmd.append(cmd)
            output_dir = Path(cmd[2])
            (output_dir / "drawing.dxf").write_bytes(dxf_bytes)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="/usr/bin/ODAFileConverter")
            parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        assert cmd[0] == "/usr/bin/ODAFileConverter"
        assert cmd[3] == "ACAD2018"   # output DXF version
        assert cmd[4] == "DXF"        # output type
        assert cmd[7] == "*.DWG"      # filter

    def test_uppercase_dxf_extension_found(self) -> None:
        """ODA converter output with .DXF (uppercase) extension should be found."""
        dxf_bytes = _make_minimal_dxf_bytes()

        def fake_run(cmd, capture_output, timeout):
            output_dir = Path(cmd[2])
            # Write with uppercase extension
            (output_dir / "DRAWING.DXF").write_bytes(dxf_bytes)
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            model = parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert isinstance(model, GeometricModel)
        assert model.source_format == DrawingFormat.DWG


# ---------------------------------------------------------------------------
# Conversion failure — non-zero exit code
# ---------------------------------------------------------------------------


class TestDWGParserConversionFailure:
    def test_nonzero_exit_code_raises_parse_error(self) -> None:
        """A non-zero ODA converter exit code should raise ParseError."""
        def fake_run(cmd, capture_output, timeout):
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout=b"", stderr=b"conversion failed"
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        err = exc_info.value
        assert err.file_format == "DWG"

    def test_parse_error_contains_exit_code(self) -> None:
        """ParseError message should include the ODA converter exit code."""
        def fake_run(cmd, capture_output, timeout):
            return subprocess.CompletedProcess(
                args=cmd, returncode=42, stdout=b"", stderr=b"some error"
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert "42" in exc_info.value.message

    def test_parse_error_contains_stderr(self) -> None:
        """ParseError message should include the ODA converter stderr output."""
        stderr_content = "ODA error: unsupported DWG version"

        def fake_run(cmd, capture_output, timeout):
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout=b"",
                stderr=stderr_content.encode(),
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert stderr_content in exc_info.value.message

    def test_parse_error_file_format_is_dwg(self) -> None:
        """ParseError raised for DWG conversion failure must have file_format == 'DWG'."""
        def fake_run(cmd, capture_output, timeout):
            return subprocess.CompletedProcess(
                args=cmd, returncode=2, stdout=b"", stderr=b"error"
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert exc_info.value.file_format == "DWG"

    def test_empty_stderr_handled_gracefully(self) -> None:
        """ParseError should be raised even when stderr is empty."""
        def fake_run(cmd, capture_output, timeout):
            return subprocess.CompletedProcess(
                args=cmd, returncode=1, stdout=b"", stderr=b""
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError):
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

    def test_no_dxf_output_raises_parse_error(self) -> None:
        """If ODA converter exits 0 but produces no DXF file, ParseError is raised."""
        def fake_run(cmd, capture_output, timeout):
            # Exit 0 but write nothing to output dir
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=b"", stderr=b""
            )

        with patch("subprocess.run", side_effect=fake_run):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert exc_info.value.file_format == "DWG"


# ---------------------------------------------------------------------------
# Converter not found / timeout
# ---------------------------------------------------------------------------


class TestDWGParserConverterErrors:
    def test_converter_not_found_raises_parse_error(self) -> None:
        """FileNotFoundError from subprocess should raise ParseError."""
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            parser = DWGParser(oda_converter_path="/nonexistent/ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        err = exc_info.value
        assert err.file_format == "DWG"
        assert "ODAFileConverter" in err.message or "not found" in err.message.lower()

    def test_converter_timeout_raises_parse_error(self) -> None:
        """subprocess.TimeoutExpired should raise ParseError."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ODAFileConverter", timeout=120),
        ):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        err = exc_info.value
        assert err.file_format == "DWG"

    def test_converter_not_found_message_mentions_path(self) -> None:
        """ParseError message should mention the converter path when not found."""
        converter_path = "/custom/path/ODAFileConverter"
        with patch("subprocess.run", side_effect=FileNotFoundError("not found")):
            parser = DWGParser(oda_converter_path=converter_path)
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "drawing.dwg")

        assert converter_path in exc_info.value.message

    def test_converter_timeout_message_mentions_source_path(self) -> None:
        """ParseError message for timeout should mention the source file path."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ODAFileConverter", timeout=120),
        ):
            parser = DWGParser(oda_converter_path="ODAFileConverter")
            with pytest.raises(ParseError) as exc_info:
                parser.parse(_make_fake_dwg_bytes(), "my_drawing.dwg")

        assert "my_drawing.dwg" in exc_info.value.message


# ---------------------------------------------------------------------------
# Constructor defaults
# ---------------------------------------------------------------------------


class TestDWGParserConstructor:
    def test_default_constructor_creates_dxf_parser(self) -> None:
        """DWGParser() with no args should create a DXFParser internally."""
        parser = DWGParser()
        assert isinstance(parser._dxf_parser, DXFParser)

    def test_custom_dxf_parser_is_used(self) -> None:
        """A custom DXFParser passed to the constructor should be used."""
        custom_dxf_parser = DXFParser()
        parser = DWGParser(dxf_parser=custom_dxf_parser)
        assert parser._dxf_parser is custom_dxf_parser

    def test_oda_converter_path_from_argument(self) -> None:
        """oda_converter_path argument should override the default."""
        parser = DWGParser(oda_converter_path="/opt/oda/ODAFileConverter")
        assert parser._oda_converter_path == "/opt/oda/ODAFileConverter"

    def test_default_oda_converter_path(self) -> None:
        """Default ODA converter path should be 'ODAFileConverter' (or from env)."""
        import os
        # Remove env var if set to test the true default
        env_val = os.environ.pop("ODA_FILE_CONVERTER", None)
        try:
            parser = DWGParser()
            assert parser._oda_converter_path == "ODAFileConverter"
        finally:
            if env_val is not None:
                os.environ["ODA_FILE_CONVERTER"] = env_val
