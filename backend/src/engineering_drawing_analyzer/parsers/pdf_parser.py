"""PDF Parser — heuristic-based extraction from engineering drawing PDFs.

Strategy
--------
1. page.get_text("dict")  → all text spans with bounding boxes
2. page.get_drawings()    → vector paths (circles → HOLE, rects → RECT, etc.)
3. Regex classification   → Dimension, Tolerance, Datum, FCF, Note, View
4. Proximity association  → link dimensions to nearest geometric feature
5. Fallback               → if extraction yields nothing, return a WARNING issue

Requirements: 1.1, 1.2, 1.3
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError as _err:  # pragma: no cover
    raise ImportError("PyMuPDF is required: pip install pymupdf") from _err

from ..exceptions import ParseError
from ..models import (
    Datum,
    Dimension,
    DrawingFormat,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    LocationReference,
    Point2D,
    TitleBlock,
    Tolerance,
    View,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Dimension: optional Ø/R prefix, number, optional tolerance.
_NUMBER_PATTERN = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_DIM_RE = re.compile(
    r"(?P<prefix>[ØøRr∅]\s*)?"
    rf"(?P<value>{_NUMBER_PATTERN})"
    rf"(?:\s*[±]\s*(?P<tol_sym>{_NUMBER_PATTERN}))?"
    rf"(?:\s*[+](?P<tol_upper>{_NUMBER_PATTERN})\s*/?\s*[-](?P<tol_lower>{_NUMBER_PATTERN}))?",
    re.UNICODE,
)

# Standalone tolerance: ±0.05
_TOL_RE = re.compile(r"[±]\s*([\d.]+)")

# Datum label: single uppercase letter, possibly boxed or prefixed
_DATUM_RE = re.compile(
    r"(?:^|\bDATUM\s*:?\s*)(?:\(|\[)?([A-Z])(?:\)|\])?(?:\s*$|\s+)",
    re.IGNORECASE,
)

# GD&T FCF symbols
_GDT_SYMBOL_CHARS = frozenset("⏤⏥○⌭⌒⌓∠⊥∥⊕◎⌯↗⌰⊘⊙⊚⊛")
_GDT_PIPE_RE = re.compile(r"^\|.+\|")
_DATUM_REF_RE = re.compile(r"\|\s*([A-Z])\s*(?:\||\Z)")
_TOL_VALUE_RE = re.compile(r"[-+]?\d*\.?\d+")
_MAT_COND_RE = re.compile(r"\b(MMC|LMC|RFS)\b", re.IGNORECASE)

# View labels
_VIEW_RE = re.compile(
    r"\b(FRONT|TOP|SIDE|RIGHT|LEFT|BOTTOM|REAR|BACK|"
    r"SECTION\s+[A-Z]-[A-Z]|DETAIL\s+[A-Z]|"
    r"VIEW\s+[A-Z]|ISO(?:METRIC)?|AUXILIARY)\b",
    re.IGNORECASE,
)

# General tolerance block
_GEN_TOL_RE = re.compile(
    r"(?:general\s+tol(?:erance)?s?\s*:?\s*|unless\s+otherwise\s+noted\s*:?\s*)"
    r"[±]\s*([\d.]+)",
    re.IGNORECASE,
)

# Unit detection
_UNIT_RE = re.compile(r"\b(mm|in|inch|inches|ft|cm)\b", re.IGNORECASE)

# Non-dimension title-block / administrative text patterns.
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_SCALE_RE = re.compile(r"^\s*(?:scale\s*:?\s*)?\d+\s*:\s*\d+\s*$", re.IGNORECASE)
_SHEET_RE = re.compile(r"\bsheet\s+\d+\s+of\s+\d+\b", re.IGNORECASE)
_DIM_EVIDENCE_RE = re.compile(
    rf"(?:[ØøRr∅]|[±°]|{_NUMBER_PATTERN}\s*(?:X|x)\s*{_NUMBER_PATTERN}|"
    rf"\d+\.\d+|\.\d+)",
    re.UNICODE,
)
_TITLE_BLOCK_WORD_RE = re.compile(
    r"\b(?:title|date|drawn\s*by|material|scale|sheet|rev|size|cal\s*poly|"
    r"solidworks|educational|project|manufacturing\s+engineering)\b",
    re.IGNORECASE,
)

# Title block keywords
_TB_KEYWORDS: dict[str, list[str]] = {
    "part_number": ["part no", "part number", "part#", "dwg no", "drawing no",
                    "drawing number", "part_number", "dwg_no"],
    "revision":    ["revision", "rev", "rev."],
    "material":    ["material", "mat.", "mat"],
    "scale":       ["scale"],
    "units":       ["units", "unit"],
}

_DEFAULT_UNIT = "mm"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _center(bbox) -> Optional[Point2D]:
    try:
        r = fitz.Rect(bbox)
        return Point2D(x=(r.x0 + r.x1) / 2.0, y=(r.y0 + r.y1) / 2.0)
    except Exception:  # noqa: BLE001
        return None


def _dist(a: Optional[Point2D], b: Optional[Point2D]) -> float:
    if a is None or b is None:
        return float("inf")
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _loc(pt: Optional[Point2D], view: str = "PAGE", label: str = "") -> LocationReference:
    return LocationReference(view_name=view, coordinates=pt, label=label or None)


def _nearest_feature(
    pt: Optional[Point2D],
    features: list[Feature],
    centers: list[Optional[Point2D]],
    threshold: float = 80.0,
) -> Optional[str]:
    if pt is None:
        return None
    best_d, best_id = threshold, None
    for feat, ctr in zip(features, centers):
        d = _dist(pt, ctr)
        if d < best_d:
            best_d, best_id = d, feat.id
    return best_id


def _is_title_block_region(span: dict, page_h: float) -> bool:
    """Return True for text in the lower title-block band of the sheet."""
    bbox = span.get("bbox")
    if bbox is None:
        return False
    pt = _center(bbox)
    return bool(pt and pt.y >= page_h * 0.86)


def _attach_dimensions_to_features(
    features: list[Feature],
    dimensions: list[Dimension],
) -> list[Feature]:
    """Keep only PDF vector candidates referenced by extracted dimensions."""
    dims_by_feature: dict[str, list[Dimension]] = {}
    for dim in dimensions:
        for feature_id in dim.associated_feature_ids:
            dims_by_feature.setdefault(feature_id, []).append(dim)

    promoted: list[Feature] = []
    for feature in features:
        dims = dims_by_feature.get(feature.id, [])
        if not dims:
            continue
        feature.dimensions = dims
        promoted.append(feature)

    kept_ids = {feature.id for feature in promoted}
    for dim in dimensions:
        dim.associated_feature_ids = [
            feature_id
            for feature_id in dim.associated_feature_ids
            if feature_id in kept_ids
        ]

    return promoted


def _filter_views_to_features(views: list[View], features: list[Feature]) -> list[View]:
    kept_ids = {feature.id for feature in features}
    if not kept_ids:
        return []
    return [
        View(
            name=view.name,
            features=[
                feature_id
                for feature_id in view.features
                if feature_id in kept_ids
            ],
        )
        for view in views
    ]


def _extract_general_tolerance(spans: list[dict]) -> Optional[Tolerance]:
    """Extract a drawing-level tolerance from the title-block tolerance text."""
    joined = " ".join(span.get("text", "").strip() for span in spans if span.get("text"))
    if not joined:
        return None

    match = _GEN_TOL_RE.search(joined)
    if not match and re.search(r"\bTOLERANCES?\b", joined, re.IGNORECASE):
        match = _TOL_RE.search(joined)
    if not match:
        return None

    try:
        value = float(match.group(1))
    except (TypeError, ValueError):
        return None
    return Tolerance(upper=value, lower=-value, is_general=True)


# ---------------------------------------------------------------------------
# Text classifiers
# ---------------------------------------------------------------------------

def _is_fcf(text: str) -> bool:
    s = text.strip()
    if any(ch in _GDT_SYMBOL_CHARS for ch in s):
        return True
    if _GDT_PIPE_RE.match(s):
        return True
    return False


def _is_dimension(text: str) -> bool:
    s = text.strip()
    if not any(ch.isdigit() for ch in s):
        return False
    if _DATE_RE.search(s) or _SCALE_RE.match(s) or _SHEET_RE.search(s):
        return False
    if _TITLE_BLOCK_WORD_RE.search(s):
        return False

    # Engineering notes can contain numbers, but they should not become
    # feature dimensions unless they carry explicit dimensional evidence.
    if not _DIM_EVIDENCE_RE.search(s):
        return False

    letters = re.findall(r"[A-Za-z]+", s)
    if letters:
        allowed_tokens = {
            "x", "X", "R", "r", "UNC", "UNF", "UNEF", "NPT", "THRU", "THROUGH",
        }
        if not all(token in allowed_tokens for token in letters):
            return False

    return bool(_DIM_RE.search(s))


def _unit_for_dimension_text(text: str, default_unit: str) -> str:
    """Infer a dimension type/unit token from annotation text."""
    stripped = text.strip()
    if "°" in stripped:
        return "ANGULAR"
    if re.match(r"^[Øø∅]", stripped):
        return "DIAMETER"
    if re.match(r"^[Rr]", stripped):
        return "RADIAL"
    return default_unit


def _parse_dim(text: str, unit: str) -> Optional[tuple[float, Optional[Tolerance]]]:
    s = re.sub(r"^[ØøRr∅]\s*", "", text.strip())
    if "°" in s:
        angle_match = re.search(rf"(?P<value>{_NUMBER_PATTERN})\s*°", s)
        if angle_match:
            try:
                return float(angle_match.group("value")), None
            except (TypeError, ValueError):
                return None

    m = _DIM_RE.search(s)
    if not m:
        return None
    try:
        value = float(m.group("value"))
    except (TypeError, ValueError):
        return None
    tol: Optional[Tolerance] = None
    if m.group("tol_sym"):
        try:
            t = float(m.group("tol_sym"))
            tol = Tolerance(upper=t, lower=-t, is_general=False)
        except ValueError:
            pass
    elif m.group("tol_upper") and m.group("tol_lower"):
        try:
            tol = Tolerance(
                upper=float(m.group("tol_upper")),
                lower=-abs(float(m.group("tol_lower"))),
                is_general=False,
            )
        except ValueError:
            pass
    return value, tol


def _parse_fcf(text: str) -> tuple[str, Optional[float], list[str], Optional[str]]:
    s = text.strip()
    symbol = next((ch for ch in s if ch in _GDT_SYMBOL_CHARS), "")
    mat = _MAT_COND_RE.search(s)
    material_condition = mat.group(1).upper() if mat else None
    datum_refs = _DATUM_REF_RE.findall(s)
    plain = s.replace(symbol, "", 1) if symbol else s
    tv_m = _TOL_VALUE_RE.search(plain)
    tol_val: Optional[float] = None
    if tv_m:
        try:
            tol_val = float(tv_m.group())
        except ValueError:
            pass
    return symbol, tol_val, datum_refs, material_condition


# ---------------------------------------------------------------------------
# Title block extraction
# ---------------------------------------------------------------------------

def _extract_title_block(spans: list[dict]) -> Optional[TitleBlock]:
    result: dict[str, Optional[str]] = {k: None for k in _TB_KEYWORDS}
    texts = [s.get("text", "").strip() for s in spans]
    for i, text in enumerate(texts):
        lower = text.lower().rstrip(":").strip()
        for field, keywords in _TB_KEYWORDS.items():
            if any(lower == kw or lower.startswith(kw) for kw in keywords):
                value: Optional[str] = None
                for kw in keywords:
                    if lower.startswith(kw):
                        remainder = text[len(kw):].lstrip(": ").strip()
                        if remainder:
                            value = remainder
                            break
                if not value and i + 1 < len(texts):
                    candidate = texts[i + 1].strip()
                    cand_lower = candidate.lower()
                    is_kw = any(
                        any(cand_lower == k or cand_lower.startswith(k) for k in kws)
                        for kws in _TB_KEYWORDS.values()
                    )
                    if candidate and not is_kw:
                        value = candidate
                if value and result[field] is None:
                    result[field] = value
                break
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
# Geometry filter
# ---------------------------------------------------------------------------

def _is_meaningful(path: dict, page_w: float, page_h: float) -> bool:
    rect = path.get("rect")
    if rect is None:
        return False
    try:
        r = fitz.Rect(rect)
    except Exception:  # noqa: BLE001
        return False
    w, h = r.width, r.height
    if w < 1.0 and h < 1.0:
        return False
    if w < 4.0 and h < 4.0:
        return False
    if w > page_w * 0.85 or h > page_h * 0.85:
        return False
    if h < 3.0 or w < 3.0:
        return False
    path_type = path.get("type", "")
    if path_type == "re":
        return True
    items = path.get("items", [])
    if not items:
        return False
    item_types = {it[0] for it in items if isinstance(it, (list, tuple)) and it}
    if "c" in item_types or "qu" in item_types:
        return True
    if path.get("fill") is not None:
        return True
    return w * h > 200


def _classify_path(path: dict) -> str:
    path_type = path.get("type", "")
    items = path.get("items", [])
    rect = path.get("rect")
    if path_type == "re":
        return "RECT"
    if rect:
        try:
            r = fitz.Rect(rect)
            w, h = r.width, r.height
            item_types = {it[0] for it in items if isinstance(it, (list, tuple)) and it}
            if ("c" in item_types or "qu" in item_types):
                aspect = max(w, h) / max(min(w, h), 1)
                if aspect < 1.4:
                    return "HOLE"
                return "CURVE"
        except Exception:  # noqa: BLE001
            pass
    if not items:
        return "PATH"
    item_types = {it[0] for it in items if isinstance(it, (list, tuple)) and it}
    if item_types == {"l"}:
        return "LINE" if len(items) == 1 else "POLYLINE"
    if "c" in item_types or "qu" in item_types:
        return "CURVE"
    return "PATH"


# ---------------------------------------------------------------------------
# PDFParser
# ---------------------------------------------------------------------------

class PDFParser:
    """Heuristic PDF parser — no ML dependencies."""

    def __init__(self, proximity_threshold: float = 20.0) -> None:
        self._proximity_threshold = proximity_threshold

    def parse(self, data: bytes, source_path: str) -> GeometricModel:
        try:
            doc: fitz.Document = fitz.open(stream=data, filetype="pdf")
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=f"Failed to open PDF '{source_path}': {exc}",
                file_format="PDF",
            ) from exc

        if doc.is_encrypted:
            raise ParseError(
                message=f"PDF '{source_path}' is encrypted.",
                file_format="PDF",
            )

        page_count = doc.page_count
        if page_count == 0:
            raise ParseError(
                message=f"PDF '{source_path}' has no pages.",
                file_format="PDF",
            )

        logger.info("PDF analysis: file=%s pages=%d size=%d bytes",
                    source_path, page_count, len(data))

        features: list[Feature] = []
        dimensions: list[Dimension] = []
        fcfs: list[FeatureControlFrame] = []
        datums: list[Datum] = []
        views: list[View] = []
        notes: list[str] = []
        title_block: Optional[TitleBlock] = None
        general_tolerance: Optional[Tolerance] = None
        unit = _DEFAULT_UNIT

        for page_idx in range(page_count):
            try:
                page = doc[page_idx]
                result = self._extract_page(page, page_idx + 1, source_path)
                features.extend(result["features"])
                dimensions.extend(result["dimensions"])
                fcfs.extend(result["fcfs"])
                datums.extend(result["datums"])
                views.extend(result["views"])
                notes.extend(result["notes"])
                if title_block is None and result["title_block"]:
                    title_block = result["title_block"]
                if general_tolerance is None and result["general_tolerance"]:
                    general_tolerance = result["general_tolerance"]
                if result["unit"] != _DEFAULT_UNIT and unit == _DEFAULT_UNIT:
                    unit = result["unit"]
            except ParseError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ParseError(
                    message=f"Error on page {page_idx + 1} of '{source_path}': {exc}",
                    file_format="PDF",
                ) from exc

        doc.close()

        logger.info(
            "PDF extraction complete: features=%d dimensions=%d tolerances=%d "
            "datums=%d fcfs=%d notes=%d views=%d",
            len(features),
            len(dimensions),
            sum(1 for d in dimensions if d.tolerance is not None),
            len(datums),
            len(fcfs),
            len(notes),
            len(views),
        )

        return GeometricModel(
            schema_version="1.0",
            source_format=DrawingFormat.PDF,
            features=features,
            dimensions=dimensions,
            datums=datums,
            feature_control_frames=fcfs,
            title_block=title_block,
            views=views,
            general_tolerance=general_tolerance,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Per-page extraction
    # ------------------------------------------------------------------

    def _extract_page(self, page: fitz.Page, page_num: int, source_path: str) -> dict:
        view_name = f"PAGE_{page_num}"
        page_rect = page.rect
        pw, ph = page_rect.width, page_rect.height

        # ---- Text extraction ----
        try:
            text_dict = page.get_text("dict")
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=f"Text extraction failed on page {page_num} of '{source_path}': {exc}",
                file_format="PDF",
            ) from exc

        all_spans = self._flatten_spans(text_dict)
        logger.debug("Page %d: %d text spans extracted", page_num, len(all_spans))

        unit = self._detect_unit(all_spans)

        # ---- Vector geometry ----
        try:
            drawings = page.get_drawings()
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=f"Vector extraction failed on page {page_num} of '{source_path}': {exc}",
                file_format="PDF",
            ) from exc

        logger.debug("Page %d: %d vector paths found", page_num, len(drawings))

        features: list[Feature] = []
        feat_centers: list[Optional[Point2D]] = []

        for path in drawings:
            if not _is_meaningful(path, pw, ph):
                continue
            ftype = _classify_path(path)
            rect = path.get("rect")
            ctr = _center(rect) if rect else None
            loc = _loc(ctr, view_name)
            features.append(Feature(id=_uid(), feature_type=ftype, location=loc))
            feat_centers.append(ctr)

        logger.debug("Page %d: %d meaningful features", page_num, len(features))

        # ---- Classify text spans ----
        dimensions: list[Dimension] = []
        fcfs: list[FeatureControlFrame] = []
        datums: list[Datum] = []
        views: list[View] = []
        notes: list[str] = []
        general_tolerance: Optional[Tolerance] = _extract_general_tolerance(all_spans)
        used: set[int] = set()

        dim_spans, fcf_spans, other_spans = [], [], []
        for idx, span in enumerate(all_spans):
            text = span.get("text", "").strip()
            if not text:
                continue
            if _is_fcf(text):
                fcf_spans.append((idx, span))
            elif _is_dimension(text):
                dim_spans.append((idx, span))
            else:
                other_spans.append((idx, span))

        # Dimensions
        for idx, span in dim_spans:
            if _is_title_block_region(span, ph):
                continue
            text = span.get("text", "").strip()
            dim_unit = _unit_for_dimension_text(text, unit)
            parsed = _parse_dim(text, dim_unit)
            if parsed is None:
                continue
            value, tol = parsed
            bbox = span.get("bbox")
            pt = _center(bbox) if bbox else None
            nearest = _nearest_feature(pt, features, feat_centers, threshold=80.0)
            dim = Dimension(
                id=_uid(),
                value=value,
                unit=dim_unit,
                tolerance=tol,
                location=_loc(pt, view_name, text),
                associated_feature_ids=[nearest] if nearest else [],
            )
            dimensions.append(dim)
            used.add(idx)

        logger.debug("Page %d: %d dimensions detected", page_num, len(dimensions))

        # FCFs
        for idx, span in fcf_spans:
            text = span.get("text", "").strip()
            symbol, tol_val, datum_refs, mat_cond = _parse_fcf(text)
            bbox = span.get("bbox")
            pt = _center(bbox) if bbox else None
            fcfs.append(FeatureControlFrame(
                id=_uid(),
                gdt_symbol=symbol,
                tolerance_value=tol_val,
                datum_references=datum_refs,
                material_condition=mat_cond,
                location=_loc(pt, view_name, text),
            ))
            used.add(idx)

        # Other spans → datums, views, general tol, notes
        feat_ids = [f.id for f in features]
        for idx, span in other_spans:
            if idx in used:
                continue
            text = span.get("text", "").strip()
            if not text:
                continue

            # General tolerance
            if general_tolerance is None:
                gt = _GEN_TOL_RE.search(text)
                if gt:
                    try:
                        tv = float(gt.group(1))
                        general_tolerance = Tolerance(upper=tv, lower=-tv, is_general=True)
                        used.add(idx)
                        continue
                    except ValueError:
                        pass

            # Datum label (short text, single letter)
            if len(text) <= 6:
                dm = _DATUM_RE.match(text)
                if dm:
                    label = dm.group(1).upper()
                    bbox = span.get("bbox")
                    pt = _center(bbox) if bbox else None
                    nearest = _nearest_feature(pt, features, feat_centers, threshold=100.0)
                    datums.append(Datum(
                        label=label,
                        feature_id=nearest or "",
                        location=_loc(pt, view_name, label),
                    ))
                    used.add(idx)
                    continue

            # View label
            vm = _VIEW_RE.search(text)
            if vm:
                views.append(View(name=vm.group(0).upper().strip(), features=feat_ids))
                used.add(idx)
                continue

            notes.append(text)

        logger.debug("Page %d: %d datums, %d views, %d notes",
                     page_num, len(datums), len(views), len(notes))

        features = _attach_dimensions_to_features(features, dimensions)
        feature_ids = {feature.id for feature in features}
        for datum in datums:
            if datum.feature_id not in feature_ids:
                datum.feature_id = ""

        views = _filter_views_to_features(views, features)
        if not views and features:
            views.append(View(name=view_name, features=[feature.id for feature in features]))

        title_block = _extract_title_block(all_spans)

        return {
            "features": features,
            "dimensions": dimensions,
            "fcfs": fcfs,
            "datums": datums,
            "views": views,
            "notes": notes,
            "title_block": title_block,
            "general_tolerance": general_tolerance,
            "unit": unit,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _flatten_spans(self, text_dict: dict) -> list[dict]:
        spans = []
        for block in text_dict.get("blocks", []):
            if block.get("type", 0) != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        spans.append(span)
        return spans

    def _detect_unit(self, spans: list[dict]) -> str:
        for span in spans:
            text = span.get("text", "").strip().lower()
            if "millimeter" in text or "millimetre" in text or text == "mm":
                return "mm"
            if "inch" in text or "inches" in text or text == "in":
                return "in"
            m = _UNIT_RE.search(text)
            if m and ("unit" in text or "dimension" in text):
                raw = m.group(1).lower()
                if raw in ("in", "inch", "inches"):
                    return "in"
                if raw == "mm":
                    return "mm"
        return _DEFAULT_UNIT
