"""Parser layer for the Engineering Drawing Analyzer.

Each parser implements the ``DrawingParser`` protocol, which converts raw
file bytes into a normalized :class:`~engineering_drawing_analyzer.models.GeometricModel`.

Requirements: 1.1, 1.2, 1.3
"""

from typing import Protocol

from ..models import GeometricModel


class DrawingParser(Protocol):
    """Protocol that every format-specific parser must satisfy."""

    def parse(self, data: bytes, source_path: str) -> GeometricModel:
        """Parse raw bytes into a :class:`GeometricModel`.

        Args:
            data:        Raw bytes of the drawing file.
            source_path: Original file path (used for error messages and
                         logging; the parser must not re-read the file).

        Returns:
            A fully-populated :class:`GeometricModel`.

        Raises:
            ParseError: If the file cannot be parsed, with location info.
        """
        ...


from .dxf_parser import DXFParser  # noqa: E402 — import after Protocol definition
from .dwg_parser import DWGParser  # noqa: E402
from .pdf_parser import PDFParser  # noqa: E402

__all__ = ["DrawingParser", "DXFParser", "DWGParser", "PDFParser"]
