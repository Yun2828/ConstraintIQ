"""Gemini Vision analyzer for engineering drawings.

Converts a PDF page to an image and sends it to Google Gemini with a
structured prompt to extract ANSI/ASME Y14.5 compliance issues.

The result is merged into the VerificationReport alongside any issues
produced by the heuristic rule engine.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

_PROMPT = """You are an expert mechanical engineer specializing in ANSI/ASME Y14.5-2018 GD&T and engineering drawing review.

Analyze this engineering drawing image and identify ALL compliance issues, errors, and missing information.

Check for:
1. Missing or incomplete dimensions (size, position, angular)
2. Missing or malformed GD&T feature control frames (tolerances, datum references)
3. Missing datum reference frame (datums A, B, C)
4. Tolerance issues (missing tolerances, stack-up problems)
5. Title block completeness (part number, revision, material, scale, units)
6. Surface finish callouts on functional surfaces
7. Hole specifications (diameter, depth, thread callout if threaded)
8. View sufficiency (enough orthographic views to fully define the part)
9. Note contradictions or ambiguities
10. Any other manufacturing readiness issues

Return ONLY a valid JSON object in this exact format, no markdown, no explanation:
{
  "drawing_id": "part name or number from title block, or 'unknown'",
  "overall_status": "Pass" or "Fail",
  "issues": [
    {
      "issue_type": "SNAKE_CASE_ISSUE_TYPE",
      "severity": "Critical" or "Warning" or "Info",
      "description": "Clear description of the issue",
      "location": {
        "view_name": "which view or area of the drawing",
        "label": "specific annotation or feature label if applicable"
      },
      "corrective_action": "Specific fix the engineer should make",
      "standard_reference": "ASME Y14.5-2018 section reference"
    }
  ],
  "systemic_patterns": ["list of repeated issue patterns if any"]
}

If the drawing has no issues, return an empty issues array and overall_status "Pass".
Be specific and actionable. Focus on real manufacturing risks."""


def _pdf_page_to_png_bytes(pdf_bytes: bytes, page_index: int = 0) -> bytes:
    """Render a PDF page to PNG bytes using PyMuPDF."""
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_index]
    # Render at 2x resolution for better readability
    mat = fitz.Matrix(2.0, 2.0)
    pix = page.get_pixmap(matrix=mat)
    png_bytes = pix.tobytes("png")
    doc.close()
    return png_bytes


def analyze_with_gemini(
    file_bytes: bytes,
    file_suffix: str,
    api_key: str,
) -> Optional[dict]:
    """Send the drawing to Gemini Vision and return the parsed JSON response.

    Args:
        file_bytes:  Raw bytes of the uploaded file.
        file_suffix: File extension: ".pdf", ".dxf", or ".dwg".
        api_key:     Google Gemini API key.

    Returns:
        Parsed JSON dict from Gemini, or None if the call fails.
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai not installed")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        # Convert to image
        if file_suffix == ".pdf":
            image_bytes = _pdf_page_to_png_bytes(file_bytes)
        else:
            # DXF/DWG — can't render visually, skip Gemini
            logger.info("Skipping Gemini analysis for %s file", file_suffix)
            return None

        # Send to Gemini
        image_part = {
            "mime_type": "image/png",
            "data": base64.b64encode(image_bytes).decode("utf-8"),
        }

        response = model.generate_content(
            [_PROMPT, image_part],
            generation_config={
                "temperature": 0.1,
                "max_output_tokens": 4096,
            },
        )

        raw = response.text.strip()

        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        return json.loads(raw)

    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON response: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini analysis failed: %s", exc)
        return None
