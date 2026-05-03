"""Symbol Detector (DPSS — Dual-Pathway Symbol Spotter) for the Engineering Drawing Analyzer.

This module provides the ``SymbolDetector`` class, which wraps the DPSS ML model
(fine-tuned on ArchCAD-400K) to detect and classify geometric primitives, GD&T
annotations, dimension callouts, and title block regions in engineering drawings.

When the actual model weights are unavailable (the common case in development /
testing environments), the detector falls back to a heuristic vector-only mode
that derives ``DetectedSymbol`` objects directly from the ``GeometricModel``'s
already-parsed data.  This makes the class useful end-to-end even without GPU
resources or the ArchCAD-400K fine-tuned weights.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    Datum,
    Dimension,
    Feature,
    FeatureControlFrame,
    GeometricModel,
    Issue,
    LocationReference,
    Point2D,
    Severity,
    TitleBlock,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DetectedSymbol
# ---------------------------------------------------------------------------


@dataclass
class DetectedSymbol:
    """A symbol detected (or heuristically inferred) from a drawing.

    Attributes:
        symbol_type:   High-level category, e.g. ``"DIMENSION"``, ``"GDT_FCF"``,
                       ``"DATUM"``, ``"TITLE_BLOCK"``, ``"FEATURE"``.
        confidence:    Detection confidence in the range ``[0.0, 1.0]``.
        primitive_ids: IDs of ``GeometricModel`` primitives that belong to this
                       symbol (features, dimensions, FCFs, datums, …).
        bounding_box:  Axis-aligned bounding box as ``(min_corner, max_corner)``.
        attributes:    Symbol-type-specific parsed attributes (free-form dict).
    """

    symbol_type: str
    confidence: float
    primitive_ids: list[str] = field(default_factory=list)
    bounding_box: tuple[Point2D, Point2D] = field(
        default_factory=lambda: (Point2D(0.0, 0.0), Point2D(0.0, 0.0))
    )
    attributes: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _location_to_bbox(location: Optional[LocationReference]) -> tuple[Point2D, Point2D]:
    """Return a degenerate bounding box centred on the location's coordinates."""
    if location is not None and location.coordinates is not None:
        pt = location.coordinates
        return (Point2D(pt.x, pt.y), Point2D(pt.x, pt.y))
    return (Point2D(0.0, 0.0), Point2D(0.0, 0.0))


def _feature_confidence(feature: Feature) -> float:
    """Heuristic confidence for a Feature based on how well-formed it is."""
    if not feature.feature_type:
        return 0.4
    score = 0.75
    if feature.dimensions:
        score = min(score + 0.05 * len(feature.dimensions), 0.95)
    if feature.feature_control_frames:
        score = min(score + 0.05, 0.95)
    return score


def _dimension_confidence(dim: Dimension) -> float:
    """Heuristic confidence for a Dimension based on completeness."""
    score = 0.70
    if dim.tolerance is not None:
        score += 0.10
    if dim.associated_feature_ids:
        score += 0.05
    return min(score, 0.95)


def _fcf_confidence(fcf: FeatureControlFrame) -> float:
    """Heuristic confidence for a FeatureControlFrame based on completeness."""
    if not fcf.gdt_symbol:
        return 0.40
    score = 0.75
    if fcf.tolerance_value is not None:
        score += 0.10
    if fcf.datum_references:
        score += 0.05
    return min(score, 0.95)


def _datum_confidence(datum: Datum) -> float:
    """Heuristic confidence for a Datum — always well-formed if it exists."""
    if datum.label and datum.feature_id:
        return 0.80
    return 0.60


def _title_block_confidence(tb: TitleBlock) -> float:
    """Heuristic confidence for a TitleBlock based on how many fields are set."""
    fields = [tb.part_number, tb.revision, tb.material, tb.scale, tb.units]
    filled = sum(1 for f in fields if f is not None and str(f).strip())
    if filled == 0:
        return 0.40
    return 0.60 + 0.07 * filled  # 0.67 … 0.95


# ---------------------------------------------------------------------------
# SymbolDetector
# ---------------------------------------------------------------------------


class SymbolDetector:
    """Detects and classifies symbols in engineering drawings.

    In production the detector loads fine-tuned DPSS weights and runs the
    dual-pathway (vector + raster) model.  When weights are unavailable the
    detector falls back to a heuristic mode that derives ``DetectedSymbol``
    objects from the ``GeometricModel``'s already-parsed data.

    Args:
        model_weights_path:   Path to the DPSS ``.pt`` / ``.bin`` weights file.
        confidence_threshold: Minimum confidence for a detection to be returned
                              by ``detect()``.  Defaults to ``0.5``.
    """

    def __init__(
        self,
        model_weights_path: str,
        confidence_threshold: float = 0.5,
    ) -> None:
        self.model_weights_path = model_weights_path
        self.confidence_threshold = confidence_threshold
        self._model_available: bool = False
        self._model = None  # placeholder for the actual DPSS model object

        # Attempt to load weights — fail gracefully rather than raising.
        try:
            self._load_weights(model_weights_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SymbolDetector: could not load model weights from %r — "
                "falling back to heuristic-only mode. Reason: %s",
                model_weights_path,
                exc,
            )
            self._model_available = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_weights(self, path: str) -> None:
        """Attempt to load DPSS model weights from *path*.

        Raises any exception on failure so the caller can set
        ``self._model_available = False``.
        """
        import os

        if not os.path.exists(path):
            raise FileNotFoundError(f"Weights file not found: {path!r}")

        # When real weights are available, load them here, e.g.:
        #   import torch
        #   self._model = DPSSModel()
        #   self._model.load_state_dict(torch.load(path, map_location="cpu"))
        #   self._model.eval()
        # For now, raise to signal unavailability so the heuristic path is used.
        raise NotImplementedError(
            "DPSS model loading is not yet implemented; "
            "ArchCAD-400K fine-tuned weights are required."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        model: GeometricModel,
        raster_image: Optional[bytes] = None,
    ) -> list[DetectedSymbol]:
        """Run symbol detection over *model* and an optional *raster_image*.

        When the DPSS model is unavailable, falls back to a heuristic
        vector-only mode that derives ``DetectedSymbol`` objects from the
        ``GeometricModel``'s existing parsed data.

        When *raster_image* is ``None``, vector-only mode is used regardless
        of whether the model is loaded.

        Args:
            model:        The ``GeometricModel`` to analyse.
            raster_image: Optional raster rendering of the drawing (PNG/JPEG
                          bytes).  Enables the dual-pathway fusion path.

        Returns:
            A list of ``DetectedSymbol`` objects whose ``confidence`` is at or
            above ``self.confidence_threshold``.
        """
        if not self._model_available:
            return self._heuristic_detect(model)

        # --- ML inference path (future implementation) ---
        if raster_image is None:
            # Vector-only mode even with a loaded model.
            return self._heuristic_detect(model)

        # When the model is available and a raster image is provided, run the
        # full dual-pathway DPSS inference here.  For now this is unreachable
        # because _load_weights always raises.
        return self._heuristic_detect(model)  # pragma: no cover

    def enrich(
        self,
        model: GeometricModel,
        symbols: list[DetectedSymbol],
    ) -> tuple[GeometricModel, list[Issue]]:
        """Merge *symbols* into *model*, updating ML confidence fields.

        Confidence thresholding rules:

        * ``confidence >= 0.8``: accepted unconditionally — update the
          feature's ``ml_confidence`` and ``ml_symbol_type``.
        * ``0.5 <= confidence < 0.8``: merged but flagged as tentative —
          set ``ml_confidence`` on the feature; do **not** overwrite an
          existing ``feature_type``.
        * ``confidence < 0.5``: discarded entirely.

        If the model was unavailable (``self._model_available is False``), a
        ``WARNING`` ``Issue`` is appended to the returned issues list.

        Args:
            model:   The ``GeometricModel`` to enrich.
            symbols: Detected symbols from ``detect()``.

        Returns:
            A ``(enriched_model, issues)`` tuple.
        """
        issues: list[Issue] = []

        # Build a fast lookup from feature id → Feature.
        feature_by_id: dict[str, Feature] = {f.id: f for f in model.features}

        for symbol in symbols:
            if symbol.confidence < 0.5:
                # Discard low-confidence detections entirely.
                continue

            if symbol.symbol_type == "FEATURE":
                self._enrich_feature_symbol(symbol, feature_by_id)
            # Other symbol types (DIMENSION, GDT_FCF, DATUM, TITLE_BLOCK) are
            # recorded in the symbol's attributes but do not currently mutate
            # the model's sub-objects — they are available for downstream use.

        if not self._model_available:
            issues.append(
                Issue(
                    issue_id=f"SD-WARN-{uuid.uuid4().hex[:8]}",
                    rule_id="SYMBOL_DETECTOR",
                    issue_type="ML_UNAVAILABLE",
                    severity=Severity.WARNING,
                    description=(
                        "ML-assisted symbol detection was unavailable "
                        "(DPSS model weights could not be loaded). "
                        "Symbol detection fell back to heuristic-only mode; "
                        "results may be incomplete."
                    ),
                    location=LocationReference(
                        view_name="N/A",
                        coordinates=None,
                        label=None,
                    ),
                    corrective_action=(
                        "Provide valid DPSS model weights via "
                        "SymbolDetector(model_weights_path=...) to enable "
                        "ML-assisted detection."
                    ),
                )
            )

        return model, issues

    # ------------------------------------------------------------------
    # Heuristic fallback
    # ------------------------------------------------------------------

    def _heuristic_detect(self, model: GeometricModel) -> list[DetectedSymbol]:
        """Derive ``DetectedSymbol`` objects from *model*'s parsed data.

        This is the primary implementation path when DPSS weights are not
        available.  Confidence scores are assigned based on how complete and
        well-formed each parsed object is.
        """
        symbols: list[DetectedSymbol] = []

        # --- Features ---
        for feature in model.features:
            conf = _feature_confidence(feature)
            if conf < self.confidence_threshold:
                continue
            symbols.append(
                DetectedSymbol(
                    symbol_type="FEATURE",
                    confidence=conf,
                    primitive_ids=[feature.id],
                    bounding_box=_location_to_bbox(feature.location),
                    attributes={
                        "feature_type": feature.feature_type,
                        "is_angular": feature.is_angular,
                        "is_threaded": feature.is_threaded,
                        "is_blind_hole": feature.is_blind_hole,
                    },
                )
            )

        # --- Dimensions ---
        for dim in model.dimensions:
            conf = _dimension_confidence(dim)
            if conf < self.confidence_threshold:
                continue
            symbols.append(
                DetectedSymbol(
                    symbol_type="DIMENSION",
                    confidence=conf,
                    primitive_ids=[dim.id],
                    bounding_box=_location_to_bbox(dim.location),
                    attributes={
                        "value": dim.value,
                        "unit": dim.unit,
                        "has_tolerance": dim.tolerance is not None,
                    },
                )
            )

        # --- Feature Control Frames (GD&T) ---
        for fcf in model.feature_control_frames:
            conf = _fcf_confidence(fcf)
            if conf < self.confidence_threshold:
                continue
            symbols.append(
                DetectedSymbol(
                    symbol_type="GDT_FCF",
                    confidence=conf,
                    primitive_ids=[fcf.id],
                    bounding_box=_location_to_bbox(fcf.location),
                    attributes={
                        "gdt_symbol": fcf.gdt_symbol,
                        "tolerance_value": fcf.tolerance_value,
                        "datum_references": list(fcf.datum_references),
                        "material_condition": fcf.material_condition,
                    },
                )
            )

        # --- Datums ---
        for datum in model.datums:
            conf = _datum_confidence(datum)
            if conf < self.confidence_threshold:
                continue
            symbols.append(
                DetectedSymbol(
                    symbol_type="DATUM",
                    confidence=conf,
                    primitive_ids=[datum.feature_id],
                    bounding_box=_location_to_bbox(datum.location),
                    attributes={
                        "label": datum.label,
                        "feature_id": datum.feature_id,
                    },
                )
            )

        # --- Title Block ---
        if model.title_block is not None:
            conf = _title_block_confidence(model.title_block)
            if conf >= self.confidence_threshold:
                tb = model.title_block
                symbols.append(
                    DetectedSymbol(
                        symbol_type="TITLE_BLOCK",
                        confidence=conf,
                        primitive_ids=[],
                        bounding_box=(Point2D(0.0, 0.0), Point2D(0.0, 0.0)),
                        attributes={
                            "part_number": tb.part_number,
                            "revision": tb.revision,
                            "material": tb.material,
                            "scale": tb.scale,
                            "units": tb.units,
                        },
                    )
                )

        return symbols

    # ------------------------------------------------------------------
    # Enrichment helpers
    # ------------------------------------------------------------------

    def _enrich_feature_symbol(
        self,
        symbol: DetectedSymbol,
        feature_by_id: dict[str, Feature],
    ) -> None:
        """Apply a FEATURE symbol's data back onto the matching Feature."""
        for pid in symbol.primitive_ids:
            feature = feature_by_id.get(pid)
            if feature is None:
                continue

            if symbol.confidence >= 0.8:
                # Unconditionally accept — update both ml fields and feature_type.
                feature.ml_confidence = symbol.confidence
                feature.ml_symbol_type = symbol.symbol_type
                detected_type = symbol.attributes.get("feature_type")
                if detected_type:
                    feature.feature_type = detected_type

            else:
                # 0.5 <= confidence < 0.8 — tentative; do NOT overwrite
                # existing feature_type (heuristic parser takes precedence).
                feature.ml_confidence = symbol.confidence
                feature.ml_symbol_type = symbol.symbol_type
                # Only set feature_type if it was previously empty.
                if not feature.feature_type:
                    detected_type = symbol.attributes.get("feature_type")
                    if detected_type:
                        feature.feature_type = detected_type
