FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN pip install --no-cache-dir \
    "duckdb>=1.1.0" \
    "fastapi>=0.115.0" \
    "httpx>=0.28.0" \
    "pydantic>=2.9.0" \
    "uvicorn>=0.34.0"

COPY backend /app/backend
COPY ingestion /app/ingestion
COPY scripts/bootstrap_data.py /app/scripts/bootstrap_data.py

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
