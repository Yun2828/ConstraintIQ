"""Unit tests for the IngestionService.

Tests:
- Files over 100 MB raise FileTooLargeError with correct size values
- Format detection for DXF, DWG, and PDF magic bytes
- Extension-based fallback detection
- Unrecognized formats raise UnsupportedFormatError listing supported formats

Requirements: 1.1, 1.3, 1.4
"""

import os
import tempfile
from pathlib import Path

import pytest

from engineering_drawing_analyzer.exceptions import (
    FileTooLargeError,
    UnsupportedFormatError,
)
from engineering_drawing_analyzer.ingestion import IngestionService
from engineering_drawing_analyzer.models import DrawingFormat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_tmp(content: bytes, suffix: str = ".bin") -> str:
    """Write *content* to a named temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    return path


# ---------------------------------------------------------------------------
# File size validation
# ---------------------------------------------------------------------------


class TestFileSizeValidation:
    def test_file_exactly_at_limit_is_accepted(self) -> None:
        """A file exactly at 100 MB should NOT raise FileTooLargeError."""
        limit = IngestionService.MAX_FILE_SIZE_BYTES
        # Write a DXF-magic file of exactly the limit size
        content = b"0\n" + b"\x00" * (limit - 2)
        path = _write_tmp(content, suffix=".dxf")
        try:
            svc = IngestionService()
            data = svc.ingest(path)
            assert len(data) == limit
        finally:
            os.unlink(path)

    def test_file_one_byte_over_limit_raises(self) -> None:
        """A file one byte over 100 MB must raise FileTooLargeError."""
        limit = IngestionService.MAX_FILE_SIZE_BYTES
        content = b"0\n" + b"\x00" * (limit - 1)  # total = limit + 1
        path = _write_tmp(content, suffix=".dxf")
        try:
            svc = IngestionService()
            with pytest.raises(FileTooLargeError) as exc_info:
                svc.ingest(path)
            err = exc_info.value
            assert err.actual_size_bytes == limit + 1
            assert err.limit_bytes == limit
        finally:
            os.unlink(path)

    def test_file_too_large_error_carries_correct_sizes(self) -> None:
        """FileTooLargeError attributes must reflect actual and limit sizes."""
        limit = IngestionService.MAX_FILE_SIZE_BYTES
        extra = 1024  # 1 KB over
        content = b"0\n" + b"\x00" * (limit - 2 + extra)
        path = _write_tmp(content, suffix=".dxf")
        try:
            svc = IngestionService()
            with pytest.raises(FileTooLargeError) as exc_info:
                svc.ingest(path)
            err = exc_info.value
            assert err.actual_size_bytes == limit + extra
            assert err.limit_bytes == limit
        finally:
            os.unlink(path)

    def test_size_check_happens_before_format_detection(self) -> None:
        """FileTooLargeError should be raised even for unknown-format files."""
        limit = IngestionService.MAX_FILE_SIZE_BYTES
        # Unknown magic bytes, but oversized
        content = b"\xDE\xAD\xBE\xEF" + b"\x00" * (limit - 2)
        path = _write_tmp(content, suffix=".xyz")
        try:
            svc = IngestionService()
            with pytest.raises(FileTooLargeError):
                svc.ingest(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Format detection — magic bytes
# ---------------------------------------------------------------------------


class TestDetectFormatMagicBytes:
    def test_pdf_magic_bytes(self) -> None:
        """Files starting with %PDF should be detected as PDF."""
        content = b"%PDF-1.4 rest of file"
        path = _write_tmp(content, suffix=".bin")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.PDF
        finally:
            os.unlink(path)

    def test_dwg_magic_bytes(self) -> None:
        """Files starting with AC should be detected as DWG."""
        content = b"AC1015 rest of dwg header"
        path = _write_tmp(content, suffix=".bin")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.DWG
        finally:
            os.unlink(path)

    def test_dxf_magic_bytes_lf(self) -> None:
        """Files starting with '0\\n' (LF) should be detected as DXF."""
        content = b"0\n  0\nSECTION\n"
        path = _write_tmp(content, suffix=".bin")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.DXF
        finally:
            os.unlink(path)

    def test_dxf_magic_bytes_crlf(self) -> None:
        """Files starting with '0\\r\\n' (CRLF) should be detected as DXF."""
        content = b"0\r\n  0\r\nSECTION\r\n"
        path = _write_tmp(content, suffix=".bin")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.DXF
        finally:
            os.unlink(path)

    def test_magic_bytes_take_precedence_over_extension(self) -> None:
        """PDF magic bytes in a .dxf file should still be detected as PDF."""
        content = b"%PDF-1.4 this is actually a pdf"
        path = _write_tmp(content, suffix=".dxf")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.PDF
        finally:
            os.unlink(path)

    def test_dwg_magic_in_pdf_extension_file(self) -> None:
        """DWG magic bytes in a .pdf file should be detected as DWG."""
        content = b"AC1015 dwg content"
        path = _write_tmp(content, suffix=".pdf")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.DWG
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Format detection — extension fallback
# ---------------------------------------------------------------------------


class TestDetectFormatExtensionFallback:
    def test_pdf_extension_fallback(self) -> None:
        """Unknown magic bytes with .pdf extension should fall back to PDF."""
        content = b"\x00\x01\x02\x03 not a real pdf header"
        path = _write_tmp(content, suffix=".pdf")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.PDF
        finally:
            os.unlink(path)

    def test_dwg_extension_fallback(self) -> None:
        """Unknown magic bytes with .dwg extension should fall back to DWG."""
        content = b"\x00\x01\x02\x03 not a real dwg header"
        path = _write_tmp(content, suffix=".dwg")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.DWG
        finally:
            os.unlink(path)

    def test_dxf_extension_fallback(self) -> None:
        """Unknown magic bytes with .dxf extension should fall back to DXF."""
        content = b"\x00\x01\x02\x03 not a real dxf header"
        path = _write_tmp(content, suffix=".dxf")
        try:
            svc = IngestionService()
            assert svc.detect_format(path) == DrawingFormat.DXF
        finally:
            os.unlink(path)

    def test_extension_case_insensitive(self) -> None:
        """Extension matching should be case-insensitive (.DXF, .Pdf, etc.)."""
        content = b"\x00\x01\x02\x03"
        for suffix in (".DXF", ".Dxf", ".PDF", ".Pdf", ".DWG", ".Dwg"):
            path = _write_tmp(content, suffix=suffix)
            try:
                svc = IngestionService()
                result = svc.detect_format(path)
                assert result in (DrawingFormat.DXF, DrawingFormat.PDF, DrawingFormat.DWG)
            finally:
                os.unlink(path)


# ---------------------------------------------------------------------------
# Unsupported format
# ---------------------------------------------------------------------------


class TestUnsupportedFormat:
    def test_unknown_magic_and_extension_raises(self) -> None:
        """Files with unrecognized magic bytes and extension raise UnsupportedFormatError."""
        content = b"\xDE\xAD\xBE\xEF unknown format"
        path = _write_tmp(content, suffix=".xyz")
        try:
            svc = IngestionService()
            with pytest.raises(UnsupportedFormatError) as exc_info:
                svc.detect_format(path)
            err = exc_info.value
            assert "DXF" in err.supported_formats
            assert "DWG" in err.supported_formats
            assert "PDF" in err.supported_formats
        finally:
            os.unlink(path)

    def test_unsupported_format_error_lists_all_supported(self) -> None:
        """UnsupportedFormatError must list all three supported formats."""
        content = b"\x00\x00\x00\x00"
        path = _write_tmp(content, suffix=".step")
        try:
            svc = IngestionService()
            with pytest.raises(UnsupportedFormatError) as exc_info:
                svc.detect_format(path)
            err = exc_info.value
            assert set(err.supported_formats) == {"DXF", "DWG", "PDF"}
        finally:
            os.unlink(path)

    def test_no_extension_unknown_magic_raises(self) -> None:
        """Files with no extension and unknown magic bytes raise UnsupportedFormatError."""
        content = b"\xCA\xFE\xBA\xBE"
        # Create a temp file then rename to remove extension
        fd, path = tempfile.mkstemp()
        os.close(fd)
        no_ext_path = path + "_noext"
        os.rename(path, no_ext_path)
        try:
            with open(no_ext_path, "wb") as fh:
                fh.write(content)
            svc = IngestionService()
            with pytest.raises(UnsupportedFormatError):
                svc.detect_format(no_ext_path)
        finally:
            os.unlink(no_ext_path)

    def test_ingest_raises_unsupported_format_error(self) -> None:
        """ingest() propagates UnsupportedFormatError for unknown formats."""
        content = b"\xDE\xAD\xBE\xEF"
        path = _write_tmp(content, suffix=".iges")
        try:
            svc = IngestionService()
            with pytest.raises(UnsupportedFormatError):
                svc.ingest(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# ingest() happy path
# ---------------------------------------------------------------------------


class TestIngestHappyPath:
    def test_ingest_returns_bytes_for_valid_dxf(self) -> None:
        """ingest() returns the raw file bytes for a valid DXF file."""
        content = b"0\n  0\nSECTION\n  2\nHEADER\n"
        path = _write_tmp(content, suffix=".dxf")
        try:
            svc = IngestionService()
            result = svc.ingest(path)
            assert result == content
        finally:
            os.unlink(path)

    def test_ingest_returns_bytes_for_valid_pdf(self) -> None:
        """ingest() returns the raw file bytes for a valid PDF file."""
        content = b"%PDF-1.4\n%%EOF\n"
        path = _write_tmp(content, suffix=".pdf")
        try:
            svc = IngestionService()
            result = svc.ingest(path)
            assert result == content
        finally:
            os.unlink(path)

    def test_ingest_returns_bytes_for_valid_dwg(self) -> None:
        """ingest() returns the raw file bytes for a valid DWG file."""
        content = b"AC1015\x00\x00\x00\x00"
        path = _write_tmp(content, suffix=".dwg")
        try:
            svc = IngestionService()
            result = svc.ingest(path)
            assert result == content
        finally:
            os.unlink(path)
