FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AML_DB_PATH=/data/aml_memory.db \
    AML_MARKDOWN_VIEW_DIR=/data/markdown

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && addgroup --system aml \
    && adduser --system --ingroup aml aml \
    && mkdir -p /data \
    && chown -R aml:aml /data

USER aml
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]

CMD ["uvicorn", "aml_memory.api:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
