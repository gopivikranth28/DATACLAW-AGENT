# dataclaw-frontend

OpenClaw channel plugin that routes messages between Dataclaw's UI and OpenClaw's agent runtime.

## Message Flow

1. Dataclaw API POSTs user message to `/dataclaw-frontend/message`
2. Plugin dispatches to OpenClaw's agent via channel system
3. Agent responses published via response broker
4. Final response persisted back to Dataclaw via `POST /chat/sessions/{id}/message`

## Environment Variables

- `DATACLAW_API_URL` — Dataclaw API base URL (default: `http://localhost:8000`)
- `DATACLAW_FRONTEND_TOKEN` — Authentication token for the bridge
