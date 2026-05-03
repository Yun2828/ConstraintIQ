"""DXF Parser — converts DXF file bytes into a GeometricModel.

Uses ``ezdxf`` (MIT-licensed) to read DXF R12 through 2018 files.
``ezdxf.recover.readbytes()`` is used for all reads so that structurally
corrupted files are repaired automatically where possible.

Supported entity types extracted from modelspace:
    LINE, ARC, CIRCLE, LWPOLYLINE  → Feature objects (geometry primitives)
    DIMENSION                       → Dimension objects
    TOLERANCE                       → FeatureControlFrame objects (GD&T FCFs)
    INSERT (title-block blocks)     → TitleBlock
    MTEXT / TEXT                    → notes / annotation text
    LEADER                          → noted but not yet modelled as a Feature

Requirements: 1.1, 1.2, 1.3
"""

from __future__ import annotations

import io
import re
import uuid
from typing import Optional

import ezdxf
import ezdxf.recover
from ezdxf.document import Drawing as EzdxfDrawing
from ezdxf.entities import (
    DXFEntity,
    DXFGraphic,
    Dimension as EzdxfDimension,
    Insert,
    LWPolyline,
    MText,
    Text,
    Tolerance as EzdxfTolerance,
)

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
# DXF $INSUNITS → unit string mapping
# ANSI/ASME Y14.5 drawings are typically inches (1) or millimetres (4).
# ---------------------------------------------------------------------------
_INSUNITS_MAP: dict[int, str] = {
    0: "unitless",
    1: "in",
    2: "ft",
    3: "mi",
    4: "mm",
    5: "cm",
    6: "m",
    7: "km",
    8: "microinch",
    9: "mil",
    10: "yd",
    11: "angstrom",
    12: "nm",
    13: "micron",
    14: "dm",
    15: "dm",
    16: "hm",
    17: "Gm",
    18: "AU",
    19: "ly",
    20: "parsec",
}

# ---------------------------------------------------------------------------
# GD&T tolerance string parsing helpers
# ---------------------------------------------------------------------------

# ANSI/ASME Y14.5-2018 standard GD&T characteristic symbols (Unicode)
_GDT_SYMBOLS: dict[str, str] = {
    # Straightness
    "straightness": "⏤",
    # Flatness
    "flatness": "⏥",
    # Circularity / roundness
    "circularity": "○",
    "roundness": "○",
    # Cylindricity
    "cylindricity": "⌭",
    # Profile of a line
    "profile of a line": "⌒",
    # Profile of a surface
    "profile of a surface": "⌓",
    # Angularity
    "angularity": "∠",
    # Perpendicularity
    "perpendicularity": "⊥",
    # Parallelism
    "parallelism": "∥",
    # Position
    "position": "⊕",
    # Concentricity / coaxiality
    "concentricity": "◎",
    "coaxiality": "◎",
    # Symmetry
    "symmetry": "⌯",
    # Circular runout
    "circular runout": "↗",
    # Total runout
    "total runout": "⌰",
}

# DXF TOLERANCE entity encodes the FCF string using special control codes.
# The format is a series of fields separated by "|" characters, with
# embedded codes like:
#   {GDT;n}  — GD&T symbol (n is an index into the Y14.5 symbol table)
#   {DIAM}   — diameter symbol
#   {P}      — projected tolerance zone
#   {MC;n}   — material condition (0=RFS, 1=MMC, 2=LMC)
#
# We parse a simplified subset sufficient for the GeometricModel.

# Regex to strip all control-code sequences from a tolerance string
_CTRL_CODE_RE = re.compile(r"\{[^}]*\}")

# GD&T symbol index → Unicode character (per ASME Y14.5-2018 Table 3-1)
_GDT_INDEX_MAP: dict[int, str] = {
    1: "⏤",   # straightness
    2: "⏥",   # flatness
    3: "○",   # circularity
    4: "⌭",   # cylindricity
    5: "⌒",   # profile of a line
    6: "⌓",   # profile of a surface
    7: "∠",   # angularity
    8: "⊥",   # perpendicularity
    9: "∥",   # parallelism
    10: "⊕",  # position
    11: "◎",  # concentricity
    12: "⌯",  # symmetry
    13: "↗",  # circular runout
    14: "⌰",  # total runout
}

# Material condition index → string
_MC_INDEX_MAP: dict[int, str] = {
    0: "RFS",
    1: "MMC",
    2: "LMC",
}

# Regex to extract {GDT;n} codes
_GDT_CODE_RE = re.compile(r"\{GDT;(\d+)\}", re.IGNORECASE)
# Regex to extract {MC;n} codes
_MC_CODE_RE = re.compile(r"\{MC;(\d+)\}", re.IGNORECASE)
# Regex to extract a numeric tolerance value from a cleaned string
_TOL_VALUE_RE = re.compile(r"[-+]?\d*\.?\d+")

# Title-block attribute tags we look for (case-insensitive)
_TITLE_BLOCK_TAGS: dict[str, str] = {
    "part_number": "part_number",
    "partno": "part_number",
    "part no": "part_number",
    "part#": "part_number",
    "dwg_no": "part_number",
    "drawing_number": "part_number",
    "revision": "revision",
    "rev": "revision",
    "material": "material",
    "mat": "material",
    "scale": "scale",
    "units": "units",
    "unit": "units",
}


def _new_id() -> str:
    """Return a short unique identifier."""
    return str(uuid.uuid4())


def _safe_float(value: object, default: float = 0.0) -> float:
    """Convert *value* to float, returning *default* on failure."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _point_from_vec(vec: object) -> Optional[Point2D]:
    """Convert an ezdxf Vec2/Vec3 (or any sequence) to a Point2D."""
    try:
        x = float(vec[0])  # type: ignore[index]
        y = float(vec[1])  # type: ignore[index]
        return Point2D(x=x, y=y)
    except (TypeError, IndexError, ValueError):
        return None


def _location_from_point(
    point: Optional[Point2D],
    view_name: str = "MODEL",
    label: Optional[str] = None,
) -> LocationReference:
    return LocationReference(
        view_name=view_name,
        coordinates=point,
        label=label,
    )


# ---------------------------------------------------------------------------
# Tolerance-string parser
# ---------------------------------------------------------------------------


def _parse_tolerance_string(
    tol_str: str,
) -> tuple[str, Optional[float], list[str], Optional[str]]:
    """Parse a DXF TOLERANCE entity string into FCF components.

    Returns:
        (gdt_symbol, tolerance_value, datum_references, material_condition)
    """
    # Extract GD&T symbol
    gdt_symbol = ""
    gdt_match = _GDT_CODE_RE.search(tol_str)
    if gdt_match:
        idx = int(gdt_match.group(1))
        gdt_symbol = _GDT_INDEX_MAP.get(idx, f"GDT{idx}")

    # Extract material condition
    material_condition: Optional[str] = None
    mc_match = _MC_CODE_RE.search(tol_str)
    if mc_match:
        idx = int(mc_match.group(1))
        material_condition = _MC_INDEX_MAP.get(idx)

    # Strip all control codes to get the plain text fields
    plain = _CTRL_CODE_RE.sub(" ", tol_str).strip()

    # Split on "|" to get fields; the first non-empty numeric field is the
    # tolerance value; subsequent single-letter fields are datum references.
    fields = [f.strip() for f in plain.split("|") if f.strip()]

    tolerance_value: Optional[float] = None
    datum_references: list[str] = []

    for field in fields:
        # Try to parse as a tolerance value
        if tolerance_value is None:
            num_match = _TOL_VALUE_RE.search(field)
            if num_match:
                try:
                    tolerance_value = float(num_match.group())
                    continue
                except ValueError:
                    pass
        # Single uppercase letter → datum reference
        if re.fullmatch(r"[A-Z]", field):
            datum_references.append(field)

    return gdt_symbol, tolerance_value, datum_references, material_condition


# ---------------------------------------------------------------------------
# DXFParser
# ---------------------------------------------------------------------------


class DXFParser:
    """Parses DXF file bytes into a :class:`GeometricModel`.

    Uses ``ezdxf.recover.readbytes()`` for all reads so that structurally
    corrupted files are repaired automatically where possible.  If the file
    is unrecoverable, a :class:`ParseError` is raised.
    """

    def parse(self, data: bytes, source_path: str) -> GeometricModel:
        """Parse *data* (raw DXF bytes) into a :class:`GeometricModel`.

        Args:
            data:        Raw bytes of the DXF file.
            source_path: Original file path (used in error messages only).

        Returns:
            A :class:`GeometricModel` with ``source_format == DrawingFormat.DXF``.

        Raises:
            ParseError: If the file cannot be parsed or recovered.
        """
        doc = self._load_document(data, source_path)
        return self._build_model(doc, source_path)

    # ------------------------------------------------------------------
    # Document loading
    # ------------------------------------------------------------------

    def _load_document(self, data: bytes, source_path: str) -> EzdxfDrawing:
        """Load the DXF document, attempting recovery on failure."""
        try:
            doc, _ = ezdxf.recover.read(io.BytesIO(data))
            return doc
        except ezdxf.DXFStructureError as exc:
            raise ParseError(
                message=f"Unrecoverable DXF structure error in '{source_path}': {exc}",
                file_format="DXF",
                byte_offset=None,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=f"Failed to parse DXF file '{source_path}': {exc}",
                file_format="DXF",
                byte_offset=None,
            ) from exc

    # ------------------------------------------------------------------
    # Model building
    # ------------------------------------------------------------------

    def _build_model(self, doc: EzdxfDrawing, source_path: str) -> GeometricModel:
        """Walk modelspace entities and populate a GeometricModel."""
        unit = self._detect_unit(doc)

        features: list[Feature] = []
        dimensions: list[Dimension] = []
        feature_control_frames: list[FeatureControlFrame] = []
        notes: list[str] = []
        title_block: Optional[TitleBlock] = None

        try:
            msp = doc.modelspace()
        except Exception as exc:  # noqa: BLE001
            raise ParseError(
                message=f"Cannot access modelspace in '{source_path}': {exc}",
                file_format="DXF",
                byte_offset=None,
            ) from exc

        for entity in msp:
            dxftype = entity.dxftype()

            if dxftype == "LINE":
                features.append(self._entity_to_feature(entity, "LINE"))

            elif dxftype == "ARC":
                features.append(self._entity_to_feature(entity, "ARC"))

            elif dxftype == "CIRCLE":
                features.append(self._entity_to_feature(entity, "CIRCLE"))

            elif dxftype == "LWPOLYLINE":
                features.append(self._entity_to_feature(entity, "LWPOLYLINE"))

            elif dxftype == "DIMENSION":
                dim = self._extract_dimension(entity, unit)
                if dim is not None:
                    dimensions.append(dim)

            elif dxftype == "LEADER":
                # Leaders are noted but not yet modelled as standalone features
                pass

            elif dxftype == "TOLERANCE":
                fcf = self._extract_fcf(entity)
                if fcf is not None:
                    feature_control_frames.append(fcf)

            elif dxftype == "INSERT":
                tb = self._extract_title_block(entity, doc)
                if tb is not None and title_block is None:
                    title_block = tb

            elif dxftype in ("MTEXT", "TEXT"):
                text_value = self._extract_text(entity)
                if text_value:
                    notes.append(text_value)

        return GeometricModel(
            schema_version="1.0",
            source_format=DrawingFormat.DXF,
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
    # Unit detection
    # ------------------------------------------------------------------

    def _detect_unit(self, doc: EzdxfDrawing) -> str:
        """Read $INSUNITS from the drawing header and return a unit string."""
        try:
            insunits = doc.header.get("$INSUNITS", 0)
            return _INSUNITS_MAP.get(int(insunits), "mm")
        except Exception:  # noqa: BLE001
            return "mm"

    # ------------------------------------------------------------------
    # Geometry entity → Feature
    # ------------------------------------------------------------------

    def _entity_to_feature(self, entity: DXFEntity, entity_type: str) -> Feature:
        """Convert a geometry entity to a Feature."""
        point: Optional[Point2D] = None

        # Try to get a representative insertion/start point
        try:
            if hasattr(entity.dxf, "start"):
                point = _point_from_vec(entity.dxf.start)
            elif hasattr(entity.dxf, "center"):
                point = _point_from_vec(entity.dxf.center)
            elif hasattr(entity.dxf, "insert"):
                point = _point_from_vec(entity.dxf.insert)
        except Exception:  # noqa: BLE001
            pass

        feature_type = _ENTITY_TYPE_MAP.get(entity_type, entity_type)
        location = _location_from_point(point)

        return Feature(
            id=_new_id(),
            feature_type=feature_type,
            location=location,
        )

    # ------------------------------------------------------------------
    # DIMENSION entity → Dimension
    # ------------------------------------------------------------------

    def _extract_dimension(
        self, entity: DXFEntity, unit: str
    ) -> Optional[Dimension]:
        """Extract a Dimension from a DIMENSION entity."""
        try:
            # actual_measurement is the measured value stored in the DXF
            value = _safe_float(
                getattr(entity.dxf, "actual_measurement", None), default=0.0
            )

            # Insertion point of the dimension annotation
            insert_vec = getattr(entity.dxf, "insert", None)
            point = _point_from_vec(insert_vec) if insert_vec is not None else None
            location = _location_from_point(point, label=None)

            # Attempt to read explicit tolerance from the dimension style
            tolerance = self._extract_dimension_tolerance(entity)

            return Dimension(
                id=_new_id(),
                value=value,
                unit=unit,
                tolerance=tolerance,
                location=location,
                associated_feature_ids=[],
            )
        except Exception:  # noqa: BLE001
            return None

    def _extract_dimension_tolerance(
        self, entity: DXFEntity
    ) -> Optional[Tolerance]:
        """Try to extract tolerance information from a DIMENSION entity.

        DXF stores tolerance in the associated DIMSTYLE or as override
        attributes on the entity itself.  We read the override attributes
        when available.
        """
        try:
            # DIMTOL=1 means tolerances are enabled; DIMLIM=1 means limits
            dimtol = getattr(entity.dxf, "dimtol", None)
            dimlim = getattr(entity.dxf, "dimlim", None)

            if dimtol or dimlim:
                upper = _safe_float(getattr(entity.dxf, "dimtp", 0.0))
                lower = _safe_float(getattr(entity.dxf, "dimtm", 0.0))
                return Tolerance(upper=upper, lower=-abs(lower), is_general=False)
        except Exception:  # noqa: BLE001
            pass
        return None

    # ------------------------------------------------------------------
    # TOLERANCE entity → FeatureControlFrame
    # ------------------------------------------------------------------

    def _extract_fcf(self, entity: DXFEntity) -> Optional[FeatureControlFrame]:
        """Extract a FeatureControlFrame from a TOLERANCE entity."""
        try:
            # ezdxf uses 'content' for the TOLERANCE entity string (not 'string')
            tol_str: str = (
                getattr(entity.dxf, "content", None)
                or getattr(entity.dxf, "string", None)
                or ""
            )

            gdt_symbol, tolerance_value, datum_references, material_condition = (
                _parse_tolerance_string(tol_str)
            )

            insert_vec = getattr(entity.dxf, "insert", None)
            point = _point_from_vec(insert_vec) if insert_vec is not None else None
            location = _location_from_point(point)

            return FeatureControlFrame(
                id=_new_id(),
                gdt_symbol=gdt_symbol,
                tolerance_value=tolerance_value,
                datum_references=datum_references,
                material_condition=material_condition,
                location=location,
            )
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # INSERT entity → TitleBlock
    # ------------------------------------------------------------------

    def _extract_title_block(
        self, entity: DXFEntity, doc: EzdxfDrawing
    ) -> Optional[TitleBlock]:
        """Extract a TitleBlock from an INSERT entity if it references a title block.

        A block is considered a title block if its name contains "TITLE"
        (case-insensitive).
        """
        try:
            block_name: str = getattr(entity.dxf, "name", "") or ""
            if "TITLE" not in block_name.upper():
                return None

            # Collect ATTRIB entities attached to this INSERT
            attribs: dict[str, str] = {}
            if hasattr(entity, "attribs"):
                for attrib in entity.attribs:
                    tag: str = (getattr(attrib.dxf, "tag", "") or "").strip().lower()
                    value: str = (getattr(attrib.dxf, "text", "") or "").strip()
                    if tag and value:
                        attribs[tag] = value

            # Also look inside the block definition for ATTDEF defaults
            try:
                block = doc.blocks.get(block_name)
                if block is not None:
                    for blk_entity in block:
                        if blk_entity.dxftype() == "ATTDEF":
                            tag = (
                                getattr(blk_entity.dxf, "tag", "") or ""
                            ).strip().lower()
                            # ezdxf uses 'text' for the default value of ATTDEF
                            # (not 'default' — that attribute does not exist in ezdxf)
                            default = (
                                getattr(blk_entity.dxf, "text", None)
                                or getattr(blk_entity.dxf, "default", None)
                                or ""
                            ).strip()
                            # Only use default if no live attrib value was found
                            if tag and default and tag not in attribs:
                                attribs[tag] = default
            except Exception:  # noqa: BLE001
                pass

            return self._attribs_to_title_block(attribs)
        except Exception:  # noqa: BLE001
            return None

    def _attribs_to_title_block(self, attribs: dict[str, str]) -> TitleBlock:
        """Map raw attribute key/value pairs to a TitleBlock."""
        result: dict[str, Optional[str]] = {
            "part_number": None,
            "revision": None,
            "material": None,
            "scale": None,
            "units": None,
        }

        for raw_tag, value in attribs.items():
            normalized = raw_tag.strip().lower().replace("-", "_").replace(" ", "_")
            # Direct match
            if normalized in result:
                result[normalized] = value
                continue
            # Alias lookup
            alias_key = _TITLE_BLOCK_TAGS.get(normalized)
            if alias_key and result[alias_key] is None:
                result[alias_key] = value

        return TitleBlock(
            part_number=result["part_number"],
            revision=result["revision"],
            material=result["material"],
            scale=result["scale"],
            units=result["units"],
        )

    # ------------------------------------------------------------------
    # TEXT / MTEXT entity → note string
    # ------------------------------------------------------------------

    def _extract_text(self, entity: DXFEntity) -> Optional[str]:
        """Extract the text content from a TEXT or MTEXT entity."""
        try:
            if entity.dxftype() == "MTEXT":
                # MText stores content in the 'text' attribute; strip control codes
                raw: str = getattr(entity.dxf, "text", "") or ""
                # Remove MTEXT formatting codes like \P, \f, {\C1;...}, etc.
                cleaned = re.sub(r"\\[A-Za-z][^;]*;|\\[A-Za-z]|\{[^}]*\}", "", raw)
                cleaned = cleaned.strip()
                return cleaned if cleaned else None
            else:
                # TEXT entity
                raw = getattr(entity.dxf, "text", "") or ""
                return raw.strip() if raw.strip() else None
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# Entity type → semantic feature type mapping
# ---------------------------------------------------------------------------

_ENTITY_TYPE_MAP: dict[str, str] = {
    "LINE": "EDGE",
    "ARC": "ARC",
    "CIRCLE": "CIRCLE",
    "LWPOLYLINE": "POLYLINE",
}
