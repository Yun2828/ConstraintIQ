"""Custom exception classes for the Engineering Drawing Analyzer.

All exceptions carry structured attributes so callers can inspect the error
programmatically rather than parsing a message string.
"""

from typing import Optional


class ParseError(Exception):
    """Raised when a drawing file cannot be parsed into a GeometricModel.

    Attributes:
        message:     Human-readable description of the parse failure.
        file_format: The format that was being parsed (e.g. "DXF", "PDF").
        byte_offset: Byte offset in the file where parsing failed, if known.
    """

    def __init__(
        self,
        message: str,
        file_format: str,
        byte_offset: Optional[int] = None,
    ) -> None:
        self.message = message
        self.file_format = file_format
        self.byte_offset = byte_offset
        location = f" at byte offset {byte_offset}" if byte_offset is not None else ""
        super().__init__(f"[{file_format}] {message}{location}")


class FileTooLargeError(Exception):
    """Raised when an uploaded drawing file exceeds the size limit.

    Attributes:
        actual_size_bytes: The actual size of the file in bytes.
        limit_bytes:       The maximum allowed size in bytes.
    """

    def __init__(self, actual_size_bytes: int, limit_bytes: int) -> None:
        self.actual_size_bytes = actual_size_bytes
        self.limit_bytes = limit_bytes
        actual_mb = actual_size_bytes / (1024 * 1024)
        limit_mb = limit_bytes / (1024 * 1024)
        super().__init__(
            f"File size {actual_mb:.1f} MB exceeds the {limit_mb:.0f} MB limit "
            f"({actual_size_bytes} bytes > {limit_bytes} bytes)."
        )


class UnsupportedFormatError(Exception):
    """Raised when the detected drawing format is not supported.

    Attributes:
        detected_format:   The format that was detected (or attempted).
        supported_formats: List of formats the analyzer accepts.
    """

    def __init__(self, detected_format: str, supported_formats: list[str]) -> None:
        self.detected_format = detected_format
        self.supported_formats = supported_formats
        supported = ", ".join(supported_formats)
        super().__init__(
            f"Unsupported drawing format '{detected_format}'. "
            f"Supported formats: {supported}."
        )


class UnsupportedReportFormatError(Exception):
    """Raised when a report is requested in an unsupported format.

    Attributes:
        requested_format:  The format string that was requested.
        supported_formats: List of formats the report generator supports.
    """

    def __init__(self, requested_format: str, supported_formats: list[str]) -> None:
        self.requested_format = requested_format
        self.supported_formats = supported_formats
        supported = ", ".join(supported_formats)
        super().__init__(
            f"Unsupported report format '{requested_format}'. "
            f"Supported formats: {supported}."
        )
