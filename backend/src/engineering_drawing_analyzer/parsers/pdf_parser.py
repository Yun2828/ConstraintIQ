"""PDF Parser — converts PDF file bytes into a GeometricModel.

Uses ``PyMuPDF`` (imported as ``fitz``) to extract vector geometry and text
annotations from each page of a PDF engineering drawing.

Extraction strategy:
    - ``page.get_drawings()``  → vector paths (lines, rects, curves, arcs)
                                  → Feature objects (geometry primitives)
    - ``page.get_text("dict")`` → text spans with bounding boxes
                                  → Dimension, FeatureControlFrame, TitleBlock,
                                    and notes

Heuristic association:
    Text blocks that are spatially close to a vector path are associated with
    that path to form Dimension and FeatureControlFrame objects.  The
    proximity threshold is configurable (default 20 pt).

Error handling:
    If a page raises an exception during extraction, a ``ParseError`` is raised
    with the page number embedded in the message, per the design specification.

Requirements: 1.1, 1.2, 1.3
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError as _fitz_import_error:  # pragma: no cover
    raise ImportError(
        "PyMuPDF is required for PDF parsing. "
        "Install it with: pip install pymupdf"
    ) from _fitz_import_error

from ..exceptions import ParseError
from ..models import (
    Dimension,
    DrawingFormat,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    LocationReference,
    Point2D,
    TitleBlock,
    Tolerance,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum distance (in PDF points) between a text span and a path for the
# text to be considered "near" that path and associated with it.
_PROXIMITY_THRESHOLD_PT: float = 20.0

# Regex patterns for dimension value extraction
# Matches patterns like: 12.5, 12.5±0.1, 12.5+0.1/-0.05, Ø12.5, R6.25
_DIM_VALUE_RE = re.compile(
    r"(?:[ØøRr∅]\s*)?"          # optional diameter/radius prefix
    r"([-+]?\d+(?:\.\d+)?)"     # main numeric value (group 1)
    r"(?:\s*[±]\s*([\d.]+))?"   # optional ± tolerance (group 2)
    r"(?:\s*[+]([\d.]+)\s*/?\s*[-]([\d.]+))?",  # optional +upper/-lower (groups 3,4)
    re.UNICODE,
)

# Regex to detect GD&T feature control frame text
# FCF text typically starts with a GD&T symbol character
_GDT_SYMBOL_CHARS = frozenset(
    "⏤⏥○⌭⌒⌓∠⊥∥⊕◎⌯↗⌰"  # standard Y14.5 symbols
    "⊘⊙⊚⊛"               # additional common variants
)

# Regex to detect a GD&T symbol at the start of a text span
_GDT_SYMBOL_RE = re.compile(
    r"^[⏤⏥○⌭⌒⌓∠⊥∥⊕◎⌯↗⌰⊘⊙⊚⊛|]"
)

# Regex to extract datum references (single uppercase letters after a "|")
_DATUM_REF_RE = re.compile(r"\|\s*([A-Z])\s*(?:\||\Z)")

# Regex to extract a numeric tolerance value
_TOL_VALUE_RE = re.compile(r"[-+]?\d*\.?\d+")

# Material condition modifiers
_MATERIAL_CONDITION_RE = re.compile(r"\b(MMC|LMC|RFS)\b", re.IGNORECASE)

# Title block keyword patterns (case-insensitive)
_TITLE_BLOCK_KEYWORDS: dict[str, list[str]] = {
    "part_number": [
        "part no", "part number", "part#", "dwg no", "drawing no",
        "drawing number", "part_number", "dwg_no",
    ],
    "revision": ["revision", "rev", "rev."],
    "material": ["material", "mat.", "mat"],
    "scale": ["scale"],
    "units": ["units", "unit"],
}

# Regex to detect a dimension unit suffix
_UNIT_RE = re.compile(r"\b(mm|in|inch|inches|ft|cm|m)\b", re.IGNORECASE)

# Default unit when none can be detected
_DEFAULT_UNIT = "mm"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    """Return a short unique identifier."""
    return str(uuid.uuid4())


def _rect_center(rect: fitz.Rect) -> Point2D:
    """Return the center of a fitz.Rect as a Point2D."""
    return Point2D(x=(rect.x0 + rect.x1) / 2.0, y=(rect.y0 + rect.y1) / 2.0)


def _point_distance(a: Point2D, b: Point2D) -> float:
    """Euclidean distance between two Point2D objects."""
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _location_from_point(
    point: Optional[Point2D],
    view_name: str = "PAGE",
    label: Optional[str] = None,
) -> LocationReference:
    return LocationReference(view_name=view_name, coordinates=point, label=label)


def _path_center(path: dict) -> Optional[Point2D]:
    """Return the approximate center of a drawing path's bounding rect."""
    rect = path.get("rect")
    if rect is None:
        return None
    try:
        r = fitz.Rect(rect)
        return _rect_center(r)
    except Exception:  # noqa: BLE001
        return None


def _span_center(span: dict) -> Optional[Point2D]:
    """Return the center of a text span's bounding box."""
    bbox = span.get("bbox")
    if bbox is None:
        return None
    try:
        r = fitz.Rect(bbox)
        return _rect_center(r)
    except Exception:  # noqa: BLE001
        return None


def _is_near(
    point_a: Optional[Point2D],
    point_b: Optional[Point2D],
    threshold: float = _PROXIMITY_THRESHOLD_PT,
) -> bool:
    """Return True if two points are within *threshold* PDF points of each other."""
    if point_a is None or point_b is None:
        return False
    return _point_distance(point_a, point_b) <= threshold


# ---------------------------------------------------------------------------
# Text classification helpers
# ---------------------------------------------------------------------------


def _looks_like_dimension(text: str) -> bool:
    """Return True if *text* looks like a dimension annotation."""
    stripped = text.strip()
    if not stripped:
        return False
    # Must contain at least one digit
    if not any(ch.isdigit() for ch in stripped):
        return False
    # Must match the dimension pattern
    return bool(_DIM_VALUE_RE.search(stripped))


def _looks_like_fcf(text: str) -> bool:
    """Return True if *text* looks like a GD&T feature control frame."""
    stripped = text.strip()
    if not stripped:
        return False
    # Check for GD&T symbol characters
    if any(ch in _GDT_SYMBOL_CHARS for ch in stripped):
        return True
    # Check for pipe-separated FCF format: |symbol|value|datum|
    if stripped.startswith("|") and stripped.count("|") >= 2:
        return True
    return bool(_GDT_SYMBOL_RE.match(stripped))


def _parse_dimension_text(
    text: str, unit: str
) -> Optional[tuple[float, Optional[Tolerance]]]:
    """Parse a dimension text string into (value, tolerance).

    Returns None if no numeric value can be extracted.
    """
    stripped = text.strip()
    # Remove diameter/radius prefix
    stripped = re.sub(r"^[ØøRr∅]\s*", "", stripped)

    match = _DIM_VALUE_RE.search(stripped)
    if not match:
        return None

    try:
        value = float(match.group(1))
    except (TypeError, ValueError):
        return None

    tolerance: Optional[Tolerance] = None

    # ± symmetric tolerance
    if match.group(2) is not None:
        try:
            tol_val = float(match.group(2))
            tolerance = Tolerance(upper=tol_val, lower=-tol_val, is_general=False)
        except (TypeError, ValueError):
            pass

    # +upper/-lower asymmetric tolerance
    elif match.group(3) is not None and match.group(4) is not None:
        try:
            upper = float(match.group(3))
            lower = float(match.group(4))
            tolerance = Tolerance(upper=upper, lower=-abs(lower), is_general=False)
        except (TypeError, ValueError):
            pass

    return value, tolerance


def _parse_fcf_text(
    text: str,
) -> tuple[str, Optional[float], list[str], Optional[str]]:
    """Parse a GD&T feature control frame text string.

    Returns:
        (gdt_symbol, tolerance_value, datum_references, material_condition)
    """
    stripped = text.strip()

    # Extract GD&T symbol (first non-pipe, non-space character that is a symbol)
    gdt_symbol = ""
    for ch in stripped:
        if ch in _GDT_SYMBOL_CHARS:
            gdt_symbol = ch
            break

    # Extract material condition
    material_condition: Optional[str] = None
    mc_match = _MATERIAL_CONDITION_RE.search(stripped)
    if mc_match:
        material_condition = mc_match.group(1).upper()

    # Extract datum references (single uppercase letters between pipes)
    datum_references: list[str] = _DATUM_REF_RE.findall(stripped)

    # Extract tolerance value (first numeric value after the symbol)
    tolerance_value: Optional[float] = None
    # Remove the GD&T symbol and look for a number
    plain = stripped
    if gdt_symbol:
        plain = plain.replace(gdt_symbol, "", 1)
    tol_match = _TOL_VALUE_RE.search(plain)
    if tol_match:
        try:
            tolerance_value = float(tol_match.group())
        except ValueError:
            pass

    return gdt_symbol, tolerance_value, datum_references, material_condition


# ---------------------------------------------------------------------------
# Title block extraction
# ---------------------------------------------------------------------------


def _extract_title_block_from_spans(
    spans: list[dict],
) -> Optional[TitleBlock]:
    """Heuristically extract title block fields from a list of text spans.

    Looks for label/value pairs where a span contains a known title block
    keyword followed by (or near) a value span.

    Args:
        spans: List of text span dicts with "text" and "bbox" keys.

    Returns:
        A TitleBlock if any fields were found, otherwise None.
    """
    result: dict[str, Optional[str]] = {
        "part_number": None,
        "revision": None,
        "material": None,
        "scale": None,
        "units": None,
    }

    texts = [s.get("text", "").strip() for s in spans]

    for i, text in enumerate(texts):
        lower = text.lower().rstrip(":").strip()
        for field, keywords in _TITLE_BLOCK_KEYWORDS.items():
            if any(lower == kw or lower.startswith(kw) for kw in keywords):
                # The value is either in the same span (after a colon/space)
                # or in the next span
                value: Optional[str] = None

                # Check for inline value: "PART NO: ABC-123"
                for kw in keywords:
                    if lower.startswith(kw):
                        remainder = text[len(kw):].lstrip(": ").strip()
                        if remainder:
                            value = remainder
                            break

                # Fall back to the next span
                if not value and i + 1 < len(texts):
                    candidate = texts[i + 1].strip()
                    # Avoid using another keyword as a value
                    candidate_lower = candidate.lower()
                    is_keyword = any(
                        any(candidate_lower == kw or candidate_lower.startswith(kw)
                            for kw in kws)
                        for kws in _TITLE_BLOCK_KEYWORDS.values()
                    )
                    if candidate and not is_keyword:
                        value = candidate

                if value and result[field] is None:
                    result[field] = value
                break

    # Return None if no fields were found at all
    if all(v is None for v in result.values()):
        return None

    return TitleBlock(
        part_number=result["part_number"],
        revision=result["revision"],
        material=result["material"],
        scale=result["scale"],
        units=result["units"],
    )


# ---------------------------------------------------------------------------
# PDFParser
# ---------------------------------------------------------------------------


class PDFParser:
    """Parses PDF file bytes into a :class:`GeometricModel`.

    Uses ``PyMuPDF`` (``fitz``) to extract vector paths and text annotations
    from each page of the PDF.  Text near geometry is heuristically associated
    to form :class:`Dimension` and :class:`FeatureControlFrame` objects.

    Args:
        proximity_threshold: Maximum distance (PDF points) between a text
            span and a path for the text to be associated with that path.
            Defaults to 20 pt.
    """

    def __init__(self, proximity_threshold: float = _PROXIMITY_THRESHOLD_PT) -> None:
        self._proximity_threshold = proximity_threshold

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self, data: bytes, source_path: str) -> GeometricModel:
        """Parse *data* (raw PDF bytes) into a :class:`GeometricModel`.

        Args:
            data:        Raw bytes of the PDF file.
            source_path: Original file path (used in error messages only).

        Returns:
            A :class:`GeometricModel` with
            ``source_format == DrawingFormat.PDF``.

        Raises:
            ParseError: If the PDF cannot be opened, or if a page raises an
                exception during extraction (includes the page number).
        """
        try:
            doc: fitz.Document = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=f"Failed to open PDF '{source_path}': {exc}",
                file_format="PDF",
            ) from exc

        if doc.is_encrypted:
            raise ParseError(
                message=f"PDF '{source_path}' is encrypted and cannot be parsed.",
                file_format="PDF",
            )

        features: list[Feature] = []
        dimensions: list[Dimension] = []
        feature_control_frames: list[FeatureControlFrame] = []
        notes: list[str] = []
        title_block: Optional[TitleBlock] = None
        unit: str = _DEFAULT_UNIT

        page_count = doc.page_count
        if page_count == 0:
            raise ParseError(
                message=f"PDF '{source_path}' contains no pages.",
                file_format="PDF",
            )

        for page_index in range(page_count):
            try:
                page: fitz.Page = doc[page_index]
                page_number = page_index + 1  # 1-based for error messages

                (
                    page_features,
                    page_dims,
                    page_fcfs,
                    page_notes,
                    page_tb,
                    page_unit,
                ) = self._extract_page(page, page_number, source_path)

                features.extend(page_features)
                dimensions.extend(page_dims)
                feature_control_frames.extend(page_fcfs)
                notes.extend(page_notes)

                # Use the first title block found across all pages
                if page_tb is not None and title_block is None:
                    title_block = page_tb

                # Use the first non-default unit detected
                if page_unit != _DEFAULT_UNIT and unit == _DEFAULT_UNIT:
                    unit = page_unit

            except ParseError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ParseError(
                    message=(
                        f"Error extracting page {page_index + 1} of "
                        f"'{source_path}': {exc}"
                    ),
                    file_format="PDF",
                ) from exc

        doc.close()

        return GeometricModel(
            schema_version="1.0",
            source_format=DrawingFormat.PDF,
            features=features,
            dimensions=dimensions,
            datums=[],
            feature_control_frames=feature_control_frames,
            title_block=title_block,
            views=[],
            general_tolerance=None,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Per-page extraction
    # ------------------------------------------------------------------

    def _extract_page(
        self,
        page: fitz.Page,
        page_number: int,
        source_path: str,
    ) -> tuple[
        list[Feature],
        list[Dimension],
        list[FeatureControlFrame],
        list[str],
        Optional[TitleBlock],
        str,
    ]:
        """Extract all content from a single PDF page.

        Args:
            page:        The fitz.Page object.
            page_number: 1-based page number (for error messages).
            source_path: Original file path (for error messages).

        Returns:
            Tuple of (features, dimensions, fcfs, notes, title_block, unit).

        Raises:
            ParseError: On partial/corrupted page content.
        """
        view_name = f"PAGE_{page_number}"

        # ---- Extract vector paths ----------------------------------------
        try:
            drawings = page.get_drawings()
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=(
                    f"Failed to extract vector paths from page {page_number} "
                    f"of '{source_path}': {exc}"
                ),
                file_format="PDF",
            ) from exc

        # ---- Extract text spans ------------------------------------------
        try:
            text_dict = page.get_text("dict")
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=(
                    f"Failed to extract text from page {page_number} "
                    f"of '{source_path}': {exc}"
                ),
                file_format="PDF",
            ) from exc

        # Flatten all text spans from the page
        all_spans = self._flatten_spans(text_dict)

        # Detect unit from text spans
        unit = self._detect_unit(all_spans)

        # ---- Build features from paths -----------------------------------
        features: list[Feature] = []
        path_centers: list[Optional[Point2D]] = []

        for path in drawings:
            feature, center = self._path_to_feature(path, view_name)
            features.append(feature)
            path_centers.append(center)

        # ---- Classify text spans -----------------------------------------
        dimensions: list[Dimension] = []
        feature_control_frames: list[FeatureControlFrame] = []
        notes: list[str] = []
        used_span_indices: set[int] = set()

        # First pass: identify dimension and FCF spans
        dim_spans: list[tuple[int, dict]] = []
        fcf_spans: list[tuple[int, dict]] = []
        other_spans: list[tuple[int, dict]] = []

        for idx, span in enumerate(all_spans):
            text = span.get("text", "").strip()
            if not text:
                continue
            if _looks_like_fcf(text):
                fcf_spans.append((idx, span))
            elif _looks_like_dimension(text):
                dim_spans.append((idx, span))
            else:
                other_spans.append((idx, span))

        # Build Dimension objects
        for idx, span in dim_spans:
            dim = self._span_to_dimension(span, unit, view_name, path_centers)
            if dim is not None:
                dimensions.append(dim)
                used_span_indices.add(idx)

        # Build FeatureControlFrame objects
        for idx, span in fcf_spans:
            fcf = self._span_to_fcf(span, view_name)
            if fcf is not None:
                feature_control_frames.append(fcf)
                used_span_indices.add(idx)

        # Remaining spans become notes
        for idx, span in other_spans:
            if idx not in used_span_indices:
                text = span.get("text", "").strip()
                if text:
                    notes.append(text)

        # ---- Title block extraction ---------------------------------------
        title_block = _extract_title_block_from_spans(all_spans)

        return features, dimensions, feature_control_frames, notes, title_block, unit

    # ------------------------------------------------------------------
    # Path → Feature
    # ------------------------------------------------------------------

    def _path_to_feature(
        self, path: dict, view_name: str
    ) -> tuple[Feature, Optional[Point2D]]:
        """Convert a PyMuPDF drawing path dict to a Feature.

        PyMuPDF path dicts have a "type" key:
            "l" → line segment
            "c" → cubic Bézier curve
            "qu" → quadratic Bézier curve
            "re" → rectangle
            "s" → stroke (open path)
            "f" → fill (closed path)

        The path also has an "items" list of tuples describing the path
        segments, and a "rect" bounding box.

        Args:
            path:      PyMuPDF drawing path dict.
            view_name: Name of the view/page for the LocationReference.

        Returns:
            (Feature, center_point)
        """
        path_type = path.get("type", "")
        items = path.get("items", [])

        # Determine semantic feature type from path geometry
        feature_type = self._classify_path(path_type, items)

        center = _path_center(path)
        location = _location_from_point(center, view_name=view_name)

        return (
            Feature(id=_new_id(), feature_type=feature_type, location=location),
            center,
        )

    def _classify_path(self, path_type: str, items: list) -> str:
        """Classify a PDF path into a semantic feature type.

        Args:
            path_type: PyMuPDF path type string.
            items:     List of path segment tuples.

        Returns:
            A feature type string: "LINE", "ARC", "CURVE", "RECT", or "PATH".
        """
        if path_type == "re":
            return "RECT"

        if not items:
            return "PATH"

        # Inspect the first item to determine the dominant geometry type
        # PyMuPDF item tuples: ("l", p1, p2) for line, ("c", p1, p2, p3, p4) for curve
        item_types = {item[0] for item in items if isinstance(item, (list, tuple)) and item}

        if item_types == {"l"}:
            # All line segments
            if len(items) == 1:
                return "LINE"
            return "POLYLINE"
        elif "c" in item_types or "qu" in item_types:
            return "CURVE"
        else:
            return "PATH"

    # ------------------------------------------------------------------
    # Span → Dimension
    # ------------------------------------------------------------------

    def _span_to_dimension(
        self,
        span: dict,
        unit: str,
        view_name: str,
        path_centers: list[Optional[Point2D]],
    ) -> Optional[Dimension]:
        """Convert a text span to a Dimension object.

        Args:
            span:         Text span dict with "text" and "bbox" keys.
            unit:         Detected unit string for this page.
            view_name:    View name for the LocationReference.
            path_centers: Centers of all paths on the page (for association).

        Returns:
            A Dimension, or None if the text cannot be parsed.
        """
        text = span.get("text", "").strip()
        parsed = _parse_dimension_text(text, unit)
        if parsed is None:
            return None

        value, tolerance = parsed

        # Detect unit override in the text itself
        unit_match = _UNIT_RE.search(text)
        if unit_match:
            raw_unit = unit_match.group(1).lower()
            if raw_unit in ("in", "inch", "inches"):
                unit = "in"
            elif raw_unit in ("mm",):
                unit = "mm"
            elif raw_unit in ("ft",):
                unit = "ft"
            elif raw_unit in ("cm",):
                unit = "cm"
            elif raw_unit in ("m",):
                unit = "m"

        span_center = _span_center(span)
        location = _location_from_point(span_center, view_name=view_name, label=text)

        # Associate with the nearest path
        associated_feature_ids: list[str] = []
        # (We don't have feature IDs here; association is done at a higher level
        # if needed.  For now we leave this empty, consistent with DXF parser.)

        return Dimension(
            id=_new_id(),
            value=value,
            unit=unit,
            tolerance=tolerance,
            location=location,
            associated_feature_ids=associated_feature_ids,
        )

    # ------------------------------------------------------------------
    # Span → FeatureControlFrame
    # ------------------------------------------------------------------

    def _span_to_fcf(
        self, span: dict, view_name: str
    ) -> Optional[FeatureControlFrame]:
        """Convert a text span to a FeatureControlFrame object.

        Args:
            span:      Text span dict with "text" and "bbox" keys.
            view_name: View name for the LocationReference.

        Returns:
            A FeatureControlFrame, or None if the text cannot be parsed.
        """
        text = span.get("text", "").strip()
        if not text:
            return None

        gdt_symbol, tolerance_value, datum_references, material_condition = (
            _parse_fcf_text(text)
        )

        span_center_pt = _span_center(span)
        location = _location_from_point(
            span_center_pt, view_name=view_name, label=text
        )

        return FeatureControlFrame(
            id=_new_id(),
            gdt_symbol=gdt_symbol,
            tolerance_value=tolerance_value,
            datum_references=datum_references,
            material_condition=material_condition,
            location=location,
        )

    # ------------------------------------------------------------------
    # Text span flattening
    # ------------------------------------------------------------------

    def _flatten_spans(self, text_dict: dict) -> list[dict]:
        """Flatten the nested PyMuPDF text dict into a list of span dicts.

        PyMuPDF ``page.get_text("dict")`` returns a nested structure:
            {"blocks": [{"lines": [{"spans": [{"text": ..., "bbox": ...}]}]}]}

        This method flattens it to a simple list of span dicts, each with
        at least "text" and "bbox" keys.

        Args:
            text_dict: The dict returned by ``page.get_text("dict")``.

        Returns:
            Flat list of span dicts.
        """
        spans: list[dict] = []
        for block in text_dict.get("blocks", []):
            # Only process text blocks (type 0); type 1 is image blocks
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        spans.append(span)
        return spans

    # ------------------------------------------------------------------
    # Unit detection
    # ------------------------------------------------------------------

    def _detect_unit(self, spans: list[dict]) -> str:
        """Detect the drawing unit from text spans.

        Looks for explicit unit declarations like "UNITS: MM" or "ALL
        DIMENSIONS IN INCHES" in the text spans.

        Args:
            spans: Flat list of span dicts.

        Returns:
            Unit string: "mm", "in", "ft", etc.  Defaults to "mm".
        """
        for span in spans:
            text = span.get("text", "").strip().lower()
            # Look for explicit unit declarations
            if "millimeter" in text or "millimetre" in text or text == "mm":
                return "mm"
            if "inch" in text or "inches" in text or text == "in":
                return "in"
            # "units: mm" or "units: in" patterns
            unit_match = _UNIT_RE.search(text)
            if unit_match and ("unit" in text or "dimension" in text):
                raw = unit_match.group(1).lower()
                if raw in ("in", "inch", "inches"):
                    return "in"
                if raw == "mm":
                    return "mm"
        return _DEFAULT_UNIT
