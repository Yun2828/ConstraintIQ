"""Ingestion layer for the Engineering Drawing Analyzer.

Responsible for:
- Validating file size against the 100 MB limit
- Detecting the drawing format from magic bytes and file extension
- Returning raw bytes for the downstream parser

Requirements: 1.1, 1.3, 1.4
"""

import os
from pathlib import Path

from .exceptions import FileTooLargeError, UnsupportedFormatError
from .models import DrawingFormat

# Magic byte signatures for supported formats
_DXF_MAGIC_ASCII = b"0\n"       # DXF files start with "0\n" (group code 0)
_DXF_MAGIC_CRLF = b"0\r\n"     # DXF files may also start with "0\r\n"
_DWG_MAGIC = b"AC"              # DWG files start with "AC" (0x41 0x43)
_PDF_MAGIC = b"%PDF"            # PDF files start with "%PDF" (0x25 0x50 0x44 0x46)

# Number of bytes to read for magic byte detection
_MAGIC_READ_BYTES = 8

_SUPPORTED_FORMATS = ["DXF", "DWG", "PDF"]


class IngestionService:
    """Validates and ingests engineering drawing files.

    Validates file size and detects the drawing format before handing off
    raw bytes to the appropriate parser.
    """

    MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MB

    def ingest(self, file_path: str) -> bytes:
        """Validate file size, detect format, and return raw file bytes.

        Args:
            file_path: Path to the drawing file on disk.

        Returns:
            Raw bytes of the file, ready for the parser.

        Raises:
            FileTooLargeError: If the file exceeds the 100 MB size limit.
            UnsupportedFormatError: If the format cannot be identified as
                DXF, DWG, or PDF.
            OSError: If the file cannot be read.
        """
        actual_size = os.path.getsize(file_path)
        if actual_size > self.MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(
                actual_size_bytes=actual_size,
                limit_bytes=self.MAX_FILE_SIZE_BYTES,
            )

        # detect_format raises UnsupportedFormatError for unknown formats
        self.detect_format(file_path)

        with open(file_path, "rb") as fh:
            return fh.read()

    def detect_format(self, file_path: str) -> DrawingFormat:
        """Detect the drawing format from magic bytes and file extension.

        Magic bytes take precedence over the file extension.  If neither
        the magic bytes nor the extension match a supported format,
        ``UnsupportedFormatError`` is raised.

        Args:
            file_path: Path to the drawing file on disk.

        Returns:
            The detected :class:`DrawingFormat`.

        Raises:
            UnsupportedFormatError: If the format cannot be identified.
            OSError: If the file cannot be read.
        """
        # Read a small header for magic byte detection
        with open(file_path, "rb") as fh:
            header = fh.read(_MAGIC_READ_BYTES)

        # --- Magic byte detection (takes precedence) ---
        if header.startswith(_PDF_MAGIC):
            return DrawingFormat.PDF

        if header.startswith(_DWG_MAGIC):
            return DrawingFormat.DWG

        # DXF is ASCII text; check both LF and CRLF line endings
        if header.startswith(_DXF_MAGIC_CRLF) or header.startswith(_DXF_MAGIC_ASCII):
            return DrawingFormat.DXF

        # --- Extension fallback ---
        ext = Path(file_path).suffix.lower()
        if ext == ".pdf":
            return DrawingFormat.PDF
        if ext == ".dwg":
            return DrawingFormat.DWG
        if ext == ".dxf":
            return DrawingFormat.DXF

        raise UnsupportedFormatError(
            detected_format=ext if ext else "(no extension)",
            supported_formats=_SUPPORTED_FORMATS,
        )
