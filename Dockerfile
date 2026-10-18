# syntax=docker/dockerfile:1.7
# ---- dashboard build ----
FROM node:22.11.0-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.12.7-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    EW_FRONTEND_DIST=/app/frontend/dist EW_DATA_DIR=/app/data
RUN useradd --create-home --uid 10001 ebolawatch
WORKDIR /app
COPY pyproject.toml README.md LICENSE.md NOTICE.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY data ./data
RUN pip install ".[postgres]"
COPY --from=web /web/dist ./frontend/dist
USER ebolawatch
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/meta')" || exit 1
CMD ["uvicorn", "ebolawatch.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
