"""Engineering Drawing Analyzer — automated verification of ANSI-standard engineering drawings."""

from .ingestion import IngestionService
from .pipeline import AnalysisPipeline
from .report_generator import ReportGenerator
from .serializer import GeometricModelSerializer, models_equivalent
from .parsers import DrawingParser, DXFParser
from .symbol_detector import DetectedSymbol, SymbolDetector
from .models import (
    Severity,
    DrawingFormat,
    ReportFormat,
    Point2D,
    LocationReference,
    Tolerance,
    Dimension,
    FeatureControlFrame,
    Datum,
    Feature,
    TitleBlock,
    View,
    GeometricModel,
    Issue,
    VerificationReport,
)
from .exceptions import (
    ParseError,
    FileTooLargeError,
    UnsupportedFormatError,
    UnsupportedReportFormatError,
)

__all__ = [
    "AnalysisPipeline",
    "Severity",
    "DrawingFormat",
    "ReportFormat",
    "Point2D",
    "LocationReference",
    "Tolerance",
    "Dimension",
    "FeatureControlFrame",
    "Datum",
    "Feature",
    "TitleBlock",
    "View",
    "GeometricModel",
    "Issue",
    "VerificationReport",
    "ParseError",
    "FileTooLargeError",
    "UnsupportedFormatError",
    "UnsupportedReportFormatError",
    "GeometricModelSerializer",
    "models_equivalent",
    "IngestionService",
    "ReportGenerator",
    "DrawingParser",
    "DXFParser",
    "DetectedSymbol",
    "SymbolDetector",
]
