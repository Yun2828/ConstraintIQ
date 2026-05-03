"""Gemini Vision analyzer for engineering drawings.

Strategy:
  1. pdfplumber extracts all text with bounding-box coordinates → structured context
  2. PyMuPDF renders the page to a high-res PNG → visual context
  3. Both are sent to gemini-1.5-pro with a detailed prompt
  4. Response is parsed into the standard report JSON format

This two-channel approach (text + image) gives Gemini both the raw content
and the spatial layout, producing far more accurate results than image-only.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a senior mechanical engineer and ANSI/ASME Y14.5-2018 GD&T expert performing a formal drawing review.

You will receive:
1. A high-resolution image of an engineering drawing
2. All text extracted from the drawing with their approximate positions (x, y in points from top-left)

Your task: identify every compliance issue, missing annotation, and manufacturing risk.

Check ALL of the following:
- DIMENSIONS: Every feature must have size dimensions (length, width, diameter, radius). Missing = Critical.
- POSITION: Every feature must be located relative to datums. Missing = Critical.
- TOLERANCES: Every dimension needs an explicit tolerance OR a general tolerance block. Missing = Critical.
- DATUM REFERENCE FRAME: Must have at least datums A, B, C on three perpendicular surfaces. Missing = Critical.
- GD&T FEATURE CONTROL FRAMES: Must have valid symbol, tolerance value, and datum references. Incomplete = Critical.
- TITLE BLOCK: Must have part number, revision, material, scale, units. Each missing field = Critical.
- SURFACE FINISH: Functional surfaces need Ra/Rz callouts. Missing = Warning.
- HOLE CALLOUTS: Holes need diameter, depth (if blind), tolerance, thread spec (if threaded). Missing = Critical.
- VIEWS: Need enough orthographic views (front, top, side) to fully define geometry. Missing = Critical.
- NOTES: Check for contradictions between notes and dimensions. Contradiction = Critical.
- ANGULAR FEATURES: Chamfers, tapers need angular dimensions. Missing = Critical.

Return ONLY valid JSON, no markdown fences, no explanation text:
{
  "drawing_id": "part number or name from title block, or filename",
  "overall_status": "Pass" or "Fail",
  "issues": [
    {
      "issue_type": "SCREAMING_SNAKE_CASE",
      "severity": "Critical",
      "description": "Specific description referencing the actual feature/annotation visible in the drawing",
      "location": {
        "view_name": "FRONT VIEW / TOP VIEW / TITLE BLOCK / GENERAL / etc",
        "label": "exact text label or feature identifier from the drawing"
      },
      "corrective_action": "Exact fix required per ASME Y14.5-2018",
      "standard_reference": "ASME Y14.5-2018 §X.X"
    }
  ],
  "systemic_patterns": []
}

Rules:
- Reference actual values you can see (e.g. "Hole Ø12.5 at position X has no tolerance")
- Do NOT invent issues that aren't visible in the drawing
- Do NOT report issues that are clearly already addressed in the drawing
- severity must be exactly "Critical", "Warning", or "Info"
- If drawing passes all checks, return empty issues array and "Pass"
"""


# ---------------------------------------------------------------------------
# Text extraction with pdfplumber
# ---------------------------------------------------------------------------

def _extract_text_with_coords(pdf_bytes: bytes) -> str:
    """Extract all text from the first PDF page with bounding box coordinates."""
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed, skipping text extraction")
        return ""

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                return ""
            page = pdf.pages[0]
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            if not words:
                return ""

            lines = ["Extracted text with positions (x0, y0, x1, y1):"]
            for w in words:
                x0 = round(w.get("x0", 0), 1)
                y0 = round(w.get("top", 0), 1)
                x1 = round(w.get("x1", 0), 1)
                y1 = round(w.get("bottom", 0), 1)
                text = w.get("text", "").strip()
                if text:
                    lines.append(f"  [{x0},{y0},{x1},{y1}] {text}")

            return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        logger.warning("pdfplumber extraction failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# PDF → high-res PNG
# ---------------------------------------------------------------------------

def _pdf_page_to_png_bytes(pdf_bytes: bytes, page_index: int = 0) -> bytes:
    """Render a PDF page to PNG at 3x resolution for maximum readability."""
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    mat = fitz.Matrix(3.0, 3.0)  # 3x = ~216 DPI, readable text and symbols
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


# ---------------------------------------------------------------------------
# Main analyzer
# ---------------------------------------------------------------------------

def analyze_with_gemini(
    file_bytes: bytes,
    file_suffix: str,
    api_key: str,
) -> Optional[dict]:
    """Analyze a drawing using Gemini 1.5 Pro with image + text context.

    Args:
        file_bytes:  Raw bytes of the uploaded file.
        file_suffix: File extension: ".pdf", ".dxf", or ".dwg".
        api_key:     Google Gemini API key.

    Returns:
        Parsed JSON dict, or None if the call fails.
    """
    if file_suffix != ".pdf":
        logger.info("Gemini analysis skipped for %s (not a PDF)", file_suffix)
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai not installed")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-pro")

        # Channel 1: high-res image
        image_bytes = _pdf_page_to_png_bytes(file_bytes)
        image_part = {
            "mime_type": "image/png",
            "data": base64.b64encode(image_bytes).decode("utf-8"),
        }

        # Channel 2: extracted text with coordinates
        text_context = _extract_text_with_coords(file_bytes)

        # Build the full prompt
        user_message = _SYSTEM_PROMPT
        if text_context:
            user_message += f"\n\n--- EXTRACTED TEXT FROM DRAWING ---\n{text_context}\n---"

        response = model.generate_content(
            [user_message, image_part],
            generation_config=genai.types.GenerationConfig(
                temperature=0.1,
                max_output_tokens=8192,
            ),
        )

        raw = response.text.strip()

        # Strip markdown code fences if Gemini adds them
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```\s*$", "", raw, flags=re.MULTILINE)
        raw = raw.strip()

        result = json.loads(raw)

        # Normalise severity casing (Gemini sometimes returns lowercase)
        for issue in result.get("issues", []):
            sev = issue.get("severity", "Info")
            sev_map = {
                "critical": "Critical",
                "warning": "Warning",
                "info": "Info",
                "error": "Critical",
                "low": "Info",
                "medium": "Warning",
                "high": "Critical",
            }
            issue["severity"] = sev_map.get(sev.lower(), sev)

        return result

    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON: %s\nRaw: %.500s", exc, raw if 'raw' in dir() else "")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini analysis failed: %s", exc, exc_info=True)
        return None
