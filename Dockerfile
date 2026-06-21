# ParkSentry -- single-container deploy.
#
# One image runs the whole stack via `npm start` (concurrently):
#   * Node/Express gateway -- serves the built React SPA, mints the Mappls token,
#     proxies /api, handles routing + assignments. Listens on the platform's $PORT.
#   * Python FastAPI ML service -- internal on :8001 (the gateway proxies to it).
#
# Build context is the repo root. Model/data artifacts (artifacts/, outputs/) are
# committed, so NO pipeline run is needed at deploy time.

FROM python:3.11-slim

# Node 22 (for `node --env-file-if-exists`) + libgomp1 (LightGBM/XGBoost runtime).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg libgomp1 \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps first so this layer caches unless requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App source (node_modules / dist / data / .env are excluded via .dockerignore).
COPY . .

# Install JS deps (root + gateway + frontend) and build the SPA.
# NODE_ENV=development on the install so the frontend build tooling (vite) is included.
RUN cd webapp && NODE_ENV=development npm run install:all && npm run build

# The gateway reads $PORT (set by Railway/Render); FastAPI stays internal on :8001.
# MAPPLS_CLIENT_ID / MAPPLS_CLIENT_SECRET are injected by the platform as env vars.
ENV PYTHONUNBUFFERED=1 \
    PORT=8000 \
    API_URL=http://127.0.0.1:8001
EXPOSE 8000

WORKDIR /app/webapp
CMD ["npm", "start"]
