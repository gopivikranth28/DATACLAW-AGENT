# Stage 1: Build the UI
FROM node:26.12.1-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS ui-build
WORKDIR /build
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ .
RUN npm run build

# Stage 2: Grab glibc Node.js binaries for the runtime image (Node 24 meets
# OpenClaw 2026.10's >=24.22.1 floor for the in-container install.sh path)
FROM node:26.12.1-slim@sha256:36793bcbb160a6a16cede1e62b93f84e26b78a972a8a4c0b879c1c12f22761ec AS node-bin

# Stage 3: API + built UI
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

# Install uv for fast Python dependency management
COPY --from=ghcr.io/astral-sh/uv:0.12.13@sha256:b485bd65cc2cf1c9a93b3554012c9c3778cf7b1b5fd3d3096ce9e1226c97e1e6 /uv /usr/local/bin/uv

# Copy full Node.js install from the glibc node image (needed by OpenClaw at runtime).
# Copying individual binaries breaks npm — it needs lib/node_modules alongside the binary.
COPY --from=node-bin /usr/local/bin/ /usr/local/bin/
COPY --from=node-bin /usr/local/lib/node_modules/ /usr/local/lib/node_modules/

# Install the OpenAI Codex CLI — used by `dataclaw/auth/codex_login.py` to
# drive browser-based / device-code OAuth flows when the user picks the
# "OpenAI Codex" agent backend. The Python SDK shells out to this binary,
# so the import alone is not sufficient.
ARG CODEX_CLI_VERSION=0.164.0
RUN npm install -g @openai/codex@${CODEX_CLI_VERSION}

# System deps: curl (for OpenClaw install script), git (so uv sync can
# clone openai-codex-app-server-sdk from its git source), and a systemctl
# replacement so OpenClaw's daemon manager works in containers. The
# replacement is pinned to a commit and checksum-verified.
ARG SYSTEMCTL_REPLACEMENT_REV=15a2509551306789afbba32a47360365355a9bc4
ARG SYSTEMCTL_REPLACEMENT_SHA256=57f9cdb22493bc74b06e125230c2009967bf6d16a7d52913fa7e9cf2e5c920de
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git \
    && curl -fsSL "https://raw.githubusercontent.com/gdraheim/docker-systemctl-replacement/${SYSTEMCTL_REPLACEMENT_REV}/files/docker/systemctl3.py" \
       -o /usr/bin/systemctl \
    && echo "${SYSTEMCTL_REPLACEMENT_SHA256}  /usr/bin/systemctl" | sha256sum -c - \
    && chmod +x /usr/bin/systemctl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /dataclaw

# Copy plugins first — pyproject.toml references them as local path deps
COPY plugins/ plugins/
# dataclaw-hermes force-includes ../../hermes-plugins/dataclaw into its build
COPY hermes-plugins/ hermes-plugins/

# Install Python dependencies (layer cache).
COPY pyproject.toml uv.lock* ./
RUN mkdir -p dataclaw && touch dataclaw/__init__.py \
    && uv sync --frozen --no-dev

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
