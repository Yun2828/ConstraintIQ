"""DWG Parser — converts DWG file bytes into a GeometricModel.

DWG is a proprietary binary format.  This parser converts DWG → DXF using
the ODA File Converter CLI (``oda_file_converter``), then delegates to
:class:`~engineering_drawing_analyzer.parsers.dxf_parser.DXFParser`.

The ODA File Converter is a free (non-commercial) command-line tool provided
by the Open Design Alliance.  It must be installed and available on ``PATH``
(or its path supplied via the ``oda_converter_path`` constructor argument).

Conversion flow::

    DWG bytes → temp input dir → oda_file_converter → temp output dir
              → read DXF bytes → DXFParser.parse() → GeometricModel

Requirements: 1.1, 1.2, 1.3
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..exceptions import ParseError
from ..models import DrawingFormat, GeometricModel
from .dxf_parser import DXFParser

# Default name / path of the ODA File Converter executable.
# Override via the ``oda_converter_path`` constructor argument or the
# ``ODA_FILE_CONVERTER`` environment variable.
_DEFAULT_ODA_CONVERTER = os.environ.get("ODA_FILE_CONVERTER", "ODAFileConverter")

# Timeout (seconds) for the ODA converter subprocess.
_CONVERTER_TIMEOUT_SECONDS = 120


class DWGParser:
    """Parses DWG file bytes into a :class:`GeometricModel`.

    Internally converts the DWG file to DXF using the ODA File Converter CLI
    and then delegates to :class:`DXFParser`.

    Args:
        oda_converter_path: Path to the ``ODAFileConverter`` executable.
            Defaults to the ``ODA_FILE_CONVERTER`` environment variable, or
            ``"ODAFileConverter"`` (i.e. resolved from ``PATH``).
        dxf_parser:         Optional pre-constructed :class:`DXFParser`
            instance.  A new one is created if not supplied.
    """

    def __init__(
        self,
        oda_converter_path: Optional[str] = None,
        dxf_parser: Optional[DXFParser] = None,
    ) -> None:
        self._oda_converter_path = oda_converter_path or _DEFAULT_ODA_CONVERTER
        self._dxf_parser = dxf_parser or DXFParser()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self, data: bytes, source_path: str) -> GeometricModel:
        """Parse *data* (raw DWG bytes) into a :class:`GeometricModel`.

        The method writes the bytes to a temporary directory, invokes the ODA
        File Converter to produce a DXF file, reads the DXF output, and
        delegates to :class:`DXFParser`.

        Args:
            data:        Raw bytes of the DWG file.
            source_path: Original file path (used in error messages only).

        Returns:
            A :class:`GeometricModel` with
            ``source_format == DrawingFormat.DWG``.

        Raises:
            ParseError: If the ODA converter fails (non-zero exit code) or if
                the resulting DXF cannot be parsed.
        """
        with tempfile.TemporaryDirectory(prefix="eda_dwg_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_dir = tmp_path / "input"
            output_dir = tmp_path / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            # Write DWG bytes to the input directory.
            # ODA File Converter requires the input to be a directory; it
            # converts all DWG/DXF files found inside it.
            dwg_filename = Path(source_path).name or "drawing.dwg"
            if not dwg_filename.lower().endswith(".dwg"):
                dwg_filename = dwg_filename + ".dwg"
            input_file = input_dir / dwg_filename
            input_file.write_bytes(data)

            # Run the ODA File Converter.
            dxf_bytes = self._convert_to_dxf(
                input_dir=input_dir,
                output_dir=output_dir,
                source_path=source_path,
            )

        # Delegate to DXFParser and override the source_format.
        model = self._dxf_parser.parse(dxf_bytes, source_path)
        model.source_format = DrawingFormat.DWG
        return model

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _convert_to_dxf(
        self,
        input_dir: Path,
        output_dir: Path,
        source_path: str,
    ) -> bytes:
        """Invoke ODA File Converter and return the resulting DXF bytes.

        ODA File Converter CLI signature::

            ODAFileConverter <input_dir> <output_dir> <version> <type>
                             <recurse> <audit> [<filter>]

        Where:
            version  — output DXF/DWG version, e.g. "ACAD2018"
            type     — output file type: "DXF" or "DWG"
            recurse  — "0" (no recursion) or "1"
            audit    — "0" (no audit) or "1" (audit/repair)
            filter   — optional glob, e.g. "*.DWG"

        Args:
            input_dir:   Directory containing the DWG file.
            output_dir:  Directory where the converted DXF will be written.
            source_path: Original source path (for error messages).

        Returns:
            Raw bytes of the converted DXF file.

        Raises:
            ParseError: If the converter exits with a non-zero code, times
                out, or produces no output file.
        """
        cmd = [
            self._oda_converter_path,
            str(input_dir),
            str(output_dir),
            "ACAD2018",  # output DXF version
            "DXF",       # output type
            "0",         # no recursion
            "1",         # audit / repair
            "*.DWG",     # filter
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=_CONVERTER_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise ParseError(
                message=(
                    f"ODA File Converter not found at '{self._oda_converter_path}'. "
                    "Install ODAFileConverter and ensure it is on PATH, or set the "
                    "ODA_FILE_CONVERTER environment variable to its full path."
                ),
                file_format="DWG",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ParseError(
                message=(
                    f"ODA File Converter timed out after "
                    f"{_CONVERTER_TIMEOUT_SECONDS}s while converting '{source_path}'."
                ),
                file_format="DWG",
            ) from exc

        if result.returncode != 0:
            stderr_text = result.stderr.decode(errors="replace").strip()
            raise ParseError(
                message=(
                    f"ODA File Converter exited with code {result.returncode} "
                    f"while converting '{source_path}'. "
                    f"stderr: {stderr_text or '(empty)'}"
                ),
                file_format="DWG",
            )

        # Locate the converted DXF file in the output directory.
        dxf_files = list(output_dir.glob("*.dxf")) + list(output_dir.glob("*.DXF"))
        if not dxf_files:
            stderr_text = result.stderr.decode(errors="replace").strip()
            raise ParseError(
                message=(
                    f"ODA File Converter produced no DXF output for '{source_path}'. "
                    f"stderr: {stderr_text or '(empty)'}"
                ),
                file_format="DWG",
            )

        # If multiple DXF files were produced (shouldn't happen for a single
        # input file), use the first one.
        return dxf_files[0].read_bytes()
