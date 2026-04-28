# dataclaw-tools

OpenClaw tool plugin that exposes Dataclaw's Python tools to OpenClaw agents.

Tools are discovered dynamically from Dataclaw's `GET /tools` endpoint at startup and registered with a configurable prefix (default: `dataclaw_`).

## Environment Variables

- `DATACLAW_API_URL` — Dataclaw API base URL (default: `http://localhost:8000`)
- `DATACLAW_TOOLS_TOKEN` — Authentication token
- `DATACLAW_TOOLS_PREFIX` — Tool name prefix (default: `dataclaw_`)
- `DATACLAW_TOOLS_OPTIONAL` — If `true`, tools that fail to register won't block startup
