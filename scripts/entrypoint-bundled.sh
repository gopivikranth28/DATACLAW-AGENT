#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Bundled entrypoint — bootstraps OpenClaw via its own CLI (matching the
# upstream scripts/docker/setup.sh flow), starts OpenClaw gateway in the
# background, then runs DataClaw (Uvicorn) in the foreground.
# ---------------------------------------------------------------------------

DATACLAW_PORT="${DATACLAW_PORT:-8000}"
OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
OPENCLAW_BRIDGE_PORT="${OPENCLAW_BRIDGE_PORT:-18790}"
OPENCLAW_CONFIG_DIR="${HOME}/.openclaw"
OPENCLAW_CONFIG_FILE="${OPENCLAW_CONFIG_DIR}/openclaw.json"

# --- Detect fresh install (mounted volume is empty) ---
FRESH_INSTALL=false
if [[ ! -f "$OPENCLAW_CONFIG_FILE" ]]; then
  FRESH_INSTALL=true
  echo "==> Fresh install detected"
fi

# --- Create OpenClaw directory tree (mirrors openclaw scripts/docker/setup.sh) ---
mkdir -p "$OPENCLAW_CONFIG_DIR"
mkdir -p "$OPENCLAW_CONFIG_DIR/identity"
mkdir -p "$OPENCLAW_CONFIG_DIR/agents/main/agent"
mkdir -p "$OPENCLAW_CONFIG_DIR/agents/main/sessions"

# --- Resolve gateway token (env → existing config → generate) ---
if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
  if [[ -f "$OPENCLAW_CONFIG_FILE" ]]; then
    OPENCLAW_GATEWAY_TOKEN="$(python3 - "$OPENCLAW_CONFIG_FILE" <<'PY' || true
import json, sys
try:
    with open(sys.argv[1]) as f:
        token = json.load(f).get("gateway", {}).get("auth", {}).get("token", "")
    if isinstance(token, str) and token.strip():
        print(token.strip(), end="")
except Exception:
    pass
PY
)"
  fi
  if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
    if command -v openssl >/dev/null 2>&1; then
      OPENCLAW_GATEWAY_TOKEN="$(openssl rand -hex 32)"
    else
      OPENCLAW_GATEWAY_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    fi
    echo "Generated new gateway token: $OPENCLAW_GATEWAY_TOKEN"
  else
    echo "Reusing gateway token from existing config"
  fi
fi
export OPENCLAW_GATEWAY_TOKEN

# Shared plugin token defaults to dataclaw-local (matches DataClaw API defaults)
DATACLAW_TOKEN="${DATACLAW_TOKEN:-${DATACLAW_FRONTEND_TOKEN:-${DATACLAW_TOOLS_TOKEN:-dataclaw-local}}}"
DATACLAW_API_URL="${DATACLAW_API_URL:-http://127.0.0.1:${DATACLAW_PORT}}"
export DATACLAW_TOKEN DATACLAW_API_URL

if [[ "$FRESH_INSTALL" == true ]]; then
  # =======================================================================
  # FRESH INSTALL — full bootstrap
  # =======================================================================

  # --- Onboarding ---
  echo "==> Running OpenClaw onboarding"
  openclaw onboard \
    --non-interactive \
    --accept-risk \
    --mode local \
    --secret-input-mode plaintext \
    --gateway-port "$OPENCLAW_GATEWAY_PORT" \
    --gateway-bind lan \
    --gateway-auth token \
    --gateway-token "$OPENCLAW_GATEWAY_TOKEN" \
    --no-install-daemon \
    --skip-skills \
    --skip-health \
    || echo "Warning: onboard exited non-zero"

  # --- Gateway defaults ---
  echo "==> Applying gateway config defaults"
  openclaw config set --batch-json "$(printf '[
    {"path":"gateway.mode","value":"local"},
    {"path":"gateway.bind","value":"lan"},
    {"path":"gateway.controlUi.allowedOrigins","value":["http://localhost:%s","http://127.0.0.1:%s"]}
  ]' "$OPENCLAW_GATEWAY_PORT" "$OPENCLAW_GATEWAY_PORT")" >/dev/null || true

  # --- Bootstrap workspace files ---
  echo "==> Bootstrapping workspace"
  WORKSPACE="${OPENCLAW_CONFIG_DIR}/workspace"
  mkdir -p "$WORKSPACE"

  cat > "$WORKSPACE/SOUL.md" << 'EOF'
# SOUL.md

## Core Truths

**Be genuinely helpful, not performatively helpful.** Skip the "Great question!" and "I'd be happy to help!" — just help. Actions speak louder than filler words.

**Have opinions.** You're allowed to disagree, prefer things, find stuff amusing or boring. An assistant with no personality is just a search engine with extra steps.

**Be resourceful before asking.** Try to figure it out. Read the file. Check the context. Search for it. Then ask if you're stuck. The goal is to come back with answers, not questions.

**Earn trust through competence.** Be careful with external actions (emails, tweets, anything public). Be bold with internal ones (reading, organizing, learning).

## Boundaries

- Private things stay private. Period.
- When in doubt, ask before acting externally.
- Never send half-baked replies to messaging surfaces.

## Vibe

Be the assistant you'd actually want to talk to. Concise when needed, thorough when it matters. Not a corporate drone. Not a sycophant. Just... good.

## Continuity

Each session, you wake up fresh. These files are your memory. Read them. Update them. They're how you persist.
EOF
  echo "  SOUL.md: created"

  cat > "$WORKSPACE/IDENTITY.md" << 'EOF'
# IDENTITY.md

- **Name:** Dataclaw
- **Creature:** AI data scientist
- **Vibe:** Sharp, resourceful, direct
EOF
  echo "  IDENTITY.md: created"

else
  # =======================================================================
  # EXISTING INSTALL — quick startup, only ensure essentials
  # =======================================================================
  echo "==> Existing config found, skipping bootstrap"

  # One-shot migration from the legacy two-plugin layout. Containers that came
  # up before the consolidation may still have `dataclaw-tools` and/or
  # `dataclaw-frontend` extensions on disk; remove them so the consolidated
  # `dataclaw` plugin owns the channel + tools cleanly. Each call is a no-op
  # if the plugin isn't installed.
  if [[ -d "$OPENCLAW_CONFIG_DIR/extensions/dataclaw-tools" \
     || -d "$OPENCLAW_CONFIG_DIR/extensions/dataclaw-frontend" ]]; then
    echo "==> Removing legacy split plugins"
    openclaw plugins uninstall dataclaw-tools 2>/dev/null || true
    openclaw plugins uninstall dataclaw-frontend 2>/dev/null || true
  fi
fi

# ---------------------------------------------------------------------------
# Run the canonical install flow BEFORE starting the gateway.
# `install_dataclaw_plugin.py` calls `install_plugin_atomic` — the same
# function the UI's "Install" button runs — so every step (build, install,
# atomic batch config with delta-only writes, the tools.alsoAllow vs
# tools.allow profile-aware branch, additive merges that preserve the user's
# existing plugins.allow/tools.allow entries, plus the channels.<id> +
# plugins.entries.<id>.* writes) stays in lockstep with the UI flow.
#
# The script stubs out _wait_for_gateway because the gateway isn't up yet —
# `openclaw plugins install` and `openclaw config set` both write to disk
# without needing a running gateway, and the gateway picks the new state up
# when we start it below.
# ---------------------------------------------------------------------------
echo "==> Installing/refreshing dataclaw plugin (canonical flow)"
( cd /dataclaw && uv run --no-sync python3 scripts/install_dataclaw_plugin.py ) \
  || echo "Warning: dataclaw plugin install/refresh exited non-zero"

echo "==> Starting OpenClaw gateway on port $OPENCLAW_GATEWAY_PORT"
openclaw gateway \
  --bind lan \
  --port "$OPENCLAW_GATEWAY_PORT" \
  --allow-unconfigured &
OPENCLAW_PID=$!

echo "==> Starting DataClaw on port $DATACLAW_PORT"
cd /dataclaw
uv run dataclaw &
DATACLAW_PID=$!

# Graceful shutdown: kill both on SIGTERM/SIGINT
cleanup() {
  echo "==> Shutting down..."
  kill "$OPENCLAW_PID" "$DATACLAW_PID" 2>/dev/null || true
  wait "$OPENCLAW_PID" "$DATACLAW_PID" 2>/dev/null || true
  exit 0
}
trap cleanup SIGTERM SIGINT

# Wait for either process to exit — if one dies, bring down the container
# so Docker's restart policy can restart both together.
wait -n "$OPENCLAW_PID" "$DATACLAW_PID"
EXIT_CODE=$?
echo "==> Process exited with code $EXIT_CODE, shutting down container..."
kill "$OPENCLAW_PID" "$DATACLAW_PID" 2>/dev/null || true
wait "$OPENCLAW_PID" "$DATACLAW_PID" 2>/dev/null || true
exit "$EXIT_CODE"
