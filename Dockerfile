# ── Backend image ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# WeasyPrint needs these system libs for PDF rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer-cached)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the FastAPI server entry point
COPY backend/main.py ./main.py

# Copy the analyzer package and install it
COPY backend/src ./src
COPY backend/pyproject.toml ./pyproject.toml
RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
