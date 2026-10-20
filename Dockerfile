# syntax=docker/dockerfile:1.7
#
# Dodaios — headless server image (the cloud-first / VPS path).
#
# Boots the FastAPI + WebSocket backend and serves the prebuilt browser UI, so a
# user reaches the full Router-Brain experience through any browser without a
# desktop install. NO desktop extras (tray, overlay, hotkey, local voice) — those
# are opt-in and useless in a headless container (see AGENTS.md, cloud-first
# doctrine). Bring your own provider keys via environment variables.
#
#   docker build -t dodaios .
#   docker run --rm -p 127.0.0.1:8000:8000 \
#       -v jarvis-data:/app/data \
#       -e JARVIS_CONTROL_API_KEY=jctl_change_me \
#       -e ANTHROPIC_API_KEY=sk-ant-... \
#       dodaios
#   # then open http://localhost:8000
#
# Or use the bundled docker-compose.yml.
#
# The volume keeps its earlier name `jarvis-data` and the configuration stays
# at /app/data/jarvis.toml: a container started from this image reads the data
# and settings an earlier image left in that volume.

# --- Stage 1: build the React UI ---------------------------------------------
# The frontend source lives in the repo; build it once here so the runtime image
# carries a ready-to-serve dist/ and needs no Node.
# Mirror the package layout, including the shared marketplace catalog imported
# by the frontend. Vite writes the bundle next to the frontend directory.
FROM node:25-slim@sha256:81db02c4b671288a03915da9534dbd54f96d0e7c24d80ccc54f5b36b2e684370 AS web
WORKDIR /build/dodaios/ui/web/frontend
COPY dodaios/ui/web/frontend/package.json dodaios/ui/web/frontend/package-lock.json ./
RUN npm ci
COPY dodaios/ui/web/frontend/ ./
COPY dodaios/marketplace/seed_catalog.json /build/dodaios/marketplace/seed_catalog.json
RUN npm run build

# --- Stage 2: runtime --------------------------------------------------------
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential/libffi: a few base deps build from sdist on slim.
# git: Jarvis-Agent lean workspaces are real isolated repositories even when
# the distribution image intentionally carries no host checkout history.
# libportaudio2: backs sounddevice (a lazy-imported base dep) so any audio path
# imports cleanly even though the container has no audio hardware.
# curl: the HEALTHCHECK below.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential libffi-dev libportaudio2 curl git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the base package only (the headless VPS contract — no [desktop] /
# [local-voice] extras). An editable install keeps PROJECT_ROOT == /app, so the
# runtime data dir resolves to the writable /app/data volume below rather than
# into read-only site-packages.
COPY pyproject.toml setup.py README.md LICENSE NOTICE ./
COPY dodaios ./dodaios
COPY --from=web /build/dodaios/ui/web/dist ./dodaios/ui/web/dist
RUN python -m pip install --upgrade pip \
 && python -m pip install -e .

# Resolve native browser packages for this Debian version while still root.
# Browser-Use itself remains isolated in its managed environment.
RUN python -m pip install playwright==1.62.0 \
 && python -m playwright install-deps chromium

# Non-root. /app/data is the only writable location at runtime.
RUN useradd --system --uid 1000 --shell /usr/sbin/nologin jarvis \
 && mkdir -p /app/data/home \
 && chown -R jarvis:jarvis /app/data
USER jarvis

EXPOSE 8000

LABEL org.opencontainers.image.title="Dodaios" \
      org.opencontainers.image.description="Dodaios headless server: the API and the browser interface" \
      org.opencontainers.image.source="https://github.com/Dodaios/Dodaios" \
      org.opencontainers.image.licenses="Apache-2.0"

# JARVIS_BIND_HOST=0.0.0.0 makes the headless listener reachable through the
# published port (the control key is the security boundary — see compose).
# JARVIS_NONINTERACTIVE skips the first-run wizard; keys come from the env.
# Config and runtime data both live in the sole writable, persisted directory;
# the application tree remains read-only to the non-root runtime user.
ENV JARVIS_BIND_HOST=0.0.0.0 \
    JARVIS_NONINTERACTIVE=1 \
    JARVIS_CONFIG=/app/data/jarvis.toml \
    JARVIS_DATA_DIR=/app/data \
    HOME=/app/data/home

# Generous start-period: first boot builds the brain in the background.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=6 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["python", "-m", "dodaios.ui.web.launcher", "--headless", "--port", "8000"]
