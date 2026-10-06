# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# RouteWright backend — production image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

# System deps stay minimal: OR-Tools needs libstdc++ which is in slim already.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# --- Builder stage: install deps into a virtual env we can copy across ---
FROM base AS builder

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.lock ./
RUN pip install --upgrade pip && \
    pip install --require-hashes -r requirements.lock

# --- Final stage ---
FROM base AS final

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY app ./app

# Run as non-root.
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8000

# Railway and Vercel both inject PORT. Default to 8000 for local docker run.
CMD ["sh", "-c", "umask 077; exec uvicorn app.main:app --no-proxy-headers --no-access-log --ws none --workers 1 --limit-concurrency 40 --host 0.0.0.0 --port ${PORT:-8000}"]
