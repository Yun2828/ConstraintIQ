"""FastAPI server for the Engineering Drawing Analyzer.

Exposes a single POST /analyze endpoint that accepts a drawing file upload
(DXF, DWG, or PDF) and returns a JSON verification report.

Deployment
----------
* Railway / Render / Fly.io: set the start command to
      uvicorn main:app --host 0.0.0.0 --port $PORT
* Local dev:
      uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add backend/src to sys.path so the package is importable whether it has
# been installed (pip install -e .) or is being run directly from the repo.
import sys

_SRC = Path(__file__).parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from engineering_drawing_analyzer import AnalysisPipeline  # noqa: E402
from engineering_drawing_analyzer.exceptions import (  # noqa: E402
    FileTooLargeError,
    ParseError,
    UnsupportedFormatError,
    UnsupportedReportFormatError,
)
from engineering_drawing_analyzer.models import ReportFormat  # noqa: E402

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Constraint IQ — Engineering Drawing Analyzer",
    description="Automated ANSI/ASME Y14.5 verification of engineering drawings.",
    version="0.1.0",
)

# Allow the Vercel frontend (and local dev) to call this API.
# In production set ALLOWED_ORIGINS to your exact Vercel URL.
_raw_origins = os.getenv("ALLOWED_ORIGINS", "*")
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One shared pipeline instance (model weights path can be set via env var).
_pipeline = AnalysisPipeline(
    model_weights_path=os.getenv("MODEL_WEIGHTS_PATH", ""),
)

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    """Liveness probe — returns 200 OK when the server is up."""
    return {"status": "ok"}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)) -> JSONResponse:
    """Analyze an engineering drawing and return a JSON verification report.

    Accepts multipart/form-data with a single ``file`` field containing a
    DXF, DWG, or PDF drawing.

    Returns the JSON verification report produced by the analysis pipeline.
    """
    # Validate content type loosely (the ingestion layer does the real check).
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".dxf", ".dwg", ".pdf"}:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix}'. "
                "Please upload a DXF, DWG, or PDF file."
            ),
        )

    # Write the upload to a temp file so the pipeline can read it by path.
    try:
        contents = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read upload: {exc}") from exc

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        report_bytes = _pipeline.analyze(
            file_path=tmp_path,
            report_format=ReportFormat.JSON,
        )
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UnsupportedFormatError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnsupportedReportFormatError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc
    finally:
        # Always clean up the temp file.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    import json

    report_data = json.loads(report_bytes)
    return JSONResponse(content=report_data)
