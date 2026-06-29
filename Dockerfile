FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY eval ./eval

RUN pip install --no-cache-dir -e ".[dev]"

COPY data ./data
COPY tests ./tests
COPY frontend ./frontend

EXPOSE 8000

# Default: serve the API + GUI. Compose overrides command per service.
CMD ["uvicorn", "inclusify_agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
