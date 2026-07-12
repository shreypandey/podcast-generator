# Single-container deploy: FastAPI serves /api/* AND the compiled Vite SPA.
# dist/ is gitignored (source-only repo), so we build the frontend here, then
# serve it from the backend's default FRONTEND_DIST_DIR (../frontend/dist).

# ---- Stage 1: build the React/Vite frontend -> /app/frontend/dist ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python backend (uv) serving the API + the built SPA ----
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app/backend

# Install Python deps first so this layer is cached unless the lockfile changes.
# --no-install-project: install dependencies only (the app runs as source, not a package).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-install-project
ENV PATH="/app/backend/.venv/bin:$PATH"

# App source, plus the compiled SPA at the path config.FRONTEND_DIST_DIR expects.
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist

# Railway injects $PORT. Single uvicorn worker keeps the in-process job queue
# (ThreadPoolExecutor max_workers=1) serialized — one pipeline at a time.
EXPOSE 8000
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
