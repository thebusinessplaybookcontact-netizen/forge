# Single-image deploy: build the PWA, then serve it from the FastAPI app so the host
# only has to run one service. The Claude and TTS keys come from the container's env.

FROM node:22-slim AS frontend
WORKDIR /build
# Copy manifests first so the dependency layer caches across source-only changes.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

# Default location for the SQLite file. Mount a volume here or the database is part of
# the container filesystem and every redeploy starts from an empty list.
RUN mkdir -p /data
ENV COACH_DATA_DIR=/data

# Don't run as root.
RUN useradd --create-home --uid 10001 coach && chown -R coach:coach /app /data
USER coach

WORKDIR /app/backend

# The API serves the built PWA from the same origin, so no CORS entries are needed.
ENV COACH_CORS_ORIGINS=""

EXPOSE 8000

# Hosts inject $PORT; fall back to 8000 for a plain `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
