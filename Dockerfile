# Stage 1: Build the UI
FROM node:22-alpine AS ui-build
WORKDIR /build
COPY ui/package.json ui/package-lock.json ./
RUN npm install
COPY ui/ .
RUN npm run build

# Stage 2: Grab glibc Node.js binaries for the runtime image
FROM node:22-slim AS node-bin

# Stage 3: API + built UI
FROM python:3.12-slim

# Install uv for fast Python dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy full Node.js install from the glibc node image (needed by OpenClaw at runtime).
# Copying individual binaries breaks npm — it needs lib/node_modules alongside the binary.
COPY --from=node-bin /usr/local/bin/ /usr/local/bin/
COPY --from=node-bin /usr/local/lib/node_modules/ /usr/local/lib/node_modules/

# Install the OpenAI Codex CLI — used by `dataclaw/auth/codex_login.py` to
# drive browser-based / device-code OAuth flows when the user picks the
# "OpenAI Codex" agent backend. The Python SDK shells out to this binary,
# so the import alone is not sufficient.
RUN npm install -g @openai/codex@latest

# System deps: curl (for OpenClaw install script), git (so uv sync can
# clone openai-codex-app-server-sdk from its git source), and a systemctl
# replacement so OpenClaw's daemon manager works in containers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git \
    && curl -fsSL https://raw.githubusercontent.com/gdraheim/docker-systemctl-replacement/master/files/docker/systemctl3.py \
       -o /usr/bin/systemctl \
    && chmod +x /usr/bin/systemctl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dataclaw

# Copy plugins first — pyproject.toml references them as local path deps
COPY plugins/ plugins/

# Install Python dependencies (layer cache).
COPY pyproject.toml uv.lock* ./
RUN mkdir -p dataclaw && touch dataclaw/__init__.py \
    && (uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev)

# Copy backend source (overwrites the stub __init__.py)
COPY dataclaw/ dataclaw/

# Copy built UI from stage 1
COPY --from=ui-build /build/dist ui/dist/

# Copy openclaw-plugins source (needed for plugin install via the Config page)
COPY openclaw-plugins/ openclaw-plugins/

# Prevent OpenClaw from detecting a headless environment — the embedded UI
# is the user's local interface, so we fake a display.
ENV DISPLAY=:0
ENV TERM=xterm-256color
ENV OPENCLAW_DISABLE_BONJOUR=1

EXPOSE 8000

CMD ["uv", "run", "dataclaw"]
