FROM python:3.12.11-slim-bookworm AS cpu
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" YOLO_CONFIG_DIR=/tmp/ultralytics \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.8.22
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project --python /usr/local/bin/python
COPY backend ./backend
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --python /usr/local/bin/python
COPY alembic.ini ./
COPY scripts ./scripts
COPY examples ./examples
RUN useradd --create-home --uid 10001 trafficvision && mkdir -p /data /models \
    && chown trafficvision:trafficvision /app /data /models
USER trafficvision
CMD ["uvicorn", "trafficvision.api:app", "--host", "0.0.0.0", "--port", "8000"]

# Optional GPU wheels are installed from a separate hash-pinned Linux lockfile.
FROM cpu AS gpu
USER root
COPY requirements-gpu.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv pip install --python /app/.venv/bin/python --torch-backend cu128 --require-hashes --reinstall -r requirements-gpu.lock
USER trafficvision
