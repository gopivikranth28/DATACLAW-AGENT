# dataclaw

Consolidated OpenClaw plugin for Dataclaw. Built and tested against OpenClaw
**2026.10.7** (`openclaw.install.minHostVersion` / `compat.pluginApi`); the
exact version is pinned as a devDependency so `tsc` checks against the same SDK
types the runtime image ships.

It provides:

1. **Tools surface** — registers every tool in Dataclaw's live tool registry as
   an OpenClaw tool named `<prefix><tool>` (default prefix `dataclaw_`). Each
   call is forwarded to Dataclaw's `POST /api/tools/{name}/call`, which runs
   Dataclaw's hooks and guardrails, executes the tool, and persists the
   `tool_call` message.
2. **Channel surface** — a `dataclaw` channel that routes messages between the
   Dataclaw web UI and OpenClaw agents and persists agent replies back to
   Dataclaw.

The plugin id and channel id are both `dataclaw`.

## Entry point

`index.ts` uses `defineChannelPluginEntry` from `openclaw/plugin-sdk/channel-core`.
The channel registers in every runtime mode; `registerFull` registers the tool
factories (it runs in both `full` and `tool-discovery` mode, the latter being
the scoped load OpenClaw uses to execute plugin tools) and, in `full` mode only,
the HTTP routes. OpenClaw loads the esbuild output `dist/index.js`
(`openclaw.runtimeExtensions`); `npm run build` produces it.

The tool list is dynamic. The Dataclaw install service writes
`src/tools/tool-manifest.generated.ts` (gitignored) and the manifest's
`contracts.tools` from the live registry before each build, so reinstall the
plugin from Config → OpenClaw after adding or removing tools.

## Configuration

All settings come from OpenClaw config; the plugin reads no environment
variables. The Dataclaw install service writes them.

| Path | Meaning |
|---|---|
| `channels.dataclaw.token` | Shared token. Sent to Dataclaw as `X-Dataclaw-Token`/`Authorization: Bearer`, and required on inbound `/dataclaw/*` requests when set. |
| `channels.dataclaw.dataclawApiUrl` | Dataclaw API base URL (default `http://localhost:8000`). |
| `channels.dataclaw.responseTimeoutMs` | How long `/dataclaw/message` waits for a reply (default 30000). |
| `channels.dataclaw.allowFrom`, `dmSecurity` | DM allowlist policy. |
| `plugins.entries.dataclaw.config.toolsPrefix` | Tool name prefix (default `dataclaw_`). |
| `plugins.entries.dataclaw.config.toolsOptional` | Register tools as optional. |

Channel settings are read per request and per tool call, so `config set`
hot reloads apply without reinstalling. The prefix applies at registration.

## HTTP routes

Registered with `auth: "plugin"` (the plugin checks the token itself):

- `POST /dataclaw/message` — dispatch a user message to the agent and wait up to
  `waitForResponseMs` for the reply.
- `GET /dataclaw/events?sessionId=…` — SSE stream of replies and edits.
- `GET /dataclaw/health` — liveness.

## Message flow

1. Dataclaw POSTs the user message to `/dataclaw/message`.
2. The plugin resolves the agent route with a channel-kind peer, so the session
   key is `agent:<agentId>:dataclaw:channel:<chat_id>`, and dispatches through
   `runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher` with
   `ChatType: "direct"` so plain agent text is delivered.
3. Replies are published to the response broker (SSE + the waiting request) and
   the final text is persisted via `POST /api/chat/sessions/{id}/message`.
4. Tool calls carry the chat id parsed from the session key (the legacy
   `:explicit:<chat_id>` form is still accepted).

## Development

```bash
npm ci
npm run build             # dist/index.js
npx tsc --noEmit -p .     # typecheck against the pinned openclaw types
```

`openclaw` 2026.10 requires Node `>=24.22.1 <25 || >=26.12.1`; `npm ci` fails
on older Node because of its preinstall check.
