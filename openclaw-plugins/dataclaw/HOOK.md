# dataclaw

Consolidated OpenClaw plugin for Dataclaw. Provides:

1. **Tools surface** — Registers Dataclaw's Python tools as OpenClaw tools (dynamic registration with a configurable prefix, default `dataclaw_`).
2. **Channel surface** — Routes user messages between the Dataclaw web UI and OpenClaw agents, persists agent responses back to Dataclaw.

The plugin id and channel id are both `dataclaw`. HTTP routes are `/dataclaw/message`, `/dataclaw/events`, `/dataclaw/health`. Channel config lives under `channels.dataclaw.*`.

## Environment Variables

- `DATACLAW_API_URL` — Dataclaw API base URL (default: `http://localhost:8000`)
- `DATACLAW_TOKEN` — Shared bearer token used by both surfaces (sent in `X-Dataclaw-Token` header). The channel surface also reads `channels.dataclaw.token` if set.
- `DATACLAW_TOOLS_PREFIX` — Tool name prefix for tools surface (default: `dataclaw_`)
- `DATACLAW_TOOLS_OPTIONAL` — If `true`/`1`, tools that fail to register won't block startup

## Channel Message Flow

1. Dataclaw API POSTs user message to `/dataclaw/message`
2. Plugin dispatches to OpenClaw's agent via channel system
3. Agent responses published via response broker
4. Final response persisted back to Dataclaw via `POST /chat/sessions/{id}/message`

## Migrating from `dataclaw-tools` / `dataclaw-frontend`

If you previously installed the two separate plugins, uninstall them once before installing this consolidated package:

```bash
openclaw plugins uninstall dataclaw-tools
openclaw plugins uninstall dataclaw-frontend
```

The DataClaw UI install button does not auto-uninstall the legacy plugins.
