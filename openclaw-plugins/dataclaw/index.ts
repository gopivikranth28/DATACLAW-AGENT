import { dataclawFrontendPlugin } from "./src/channel/channel.js";
import { registerDataclawFrontendRoutes } from "./src/channel/http-routes.js";
import { createDataclawToolsClient } from "./src/tools/client.js";
import { resolveDataclawToolsConfig } from "./src/tools/config.js";
import { DATACLAW_TOOL_MANIFEST } from "./src/tools/tool-manifest.js";
import { toOpenClawToolResult } from "./src/tools/tool-result.js";

type ToolContext = {
  sessionId?: string;
  sessionKey?: string;
  agentId?: string;
};

type ApiWithChannel = {
  registerChannel?: (registration: { plugin: unknown }) => void;
  registerHttpRoute?: (route: unknown) => void;
  registerTool: (factory: unknown, opts?: unknown) => void;
  registrationMode?: string;
  runtime?: { config?: { current?: () => unknown } };
  logger?: { info?: (m: string) => void };
};

/**
 * Custom plugin entry. We can't use `defineChannelPluginEntry` because its
 * wrapper gates `registerFull(api)` on `api.registrationMode === "full"`,
 * which means tool factories never register during the "discovery" mode load
 * OpenClaw uses for tool-execution lookup (`activate: false, toolDiscovery: true`
 * in `tools.runtimeMissing` resolution). The agent then sees the tool
 * descriptor (declared in `contracts.tools`) but execution fails with
 * "plugin tool runtime missing".
 *
 * Mode handling here:
 *   - "cli-metadata":         do nothing (no live registrations).
 *   - "discovery" / "full":   register channel + tool factories. Tool
 *                             factories are cheap — they're called only when
 *                             the agent actually invokes a tool — so
 *                             registering them in discovery mode just makes
 *                             the lookup path find them.
 *   - "full" only:            register HTTP routes (need the live HTTP server).
 *
 * `channelPlugin` is also exposed on the entry object so OpenClaw's
 * setup-time channel-plugin discovery picks it up before the runtime register
 * runs (matches what `defineChannelPluginEntry` returns).
 */
export default {
  id: "dataclaw",
  name: "Dataclaw",
  description:
    "Dataclaw integration: registers Python tools and routes UI messages between Dataclaw and OpenClaw.",
  channelPlugin: dataclawFrontendPlugin,
  register(api: ApiWithChannel) {
    const mode = api.registrationMode;
    if (mode === "cli-metadata") return;

    api.registerChannel?.({ plugin: dataclawFrontendPlugin });

    // Tool factories: register in discovery + full so the tool-execution
    // lookup path (which loads with activate: false → discovery mode) can
    // resolve `dataclaw_*` runtime tools.
    const fullCfg = api.runtime?.config?.current?.();
    const cfg = resolveDataclawToolsConfig(fullCfg as never);
    const client = createDataclawToolsClient(cfg);
    const registered = new Set<string>();
    for (const tool of DATACLAW_TOOL_MANIFEST) {
      const openClawName = `${cfg.prefix}${tool.name}`;
      if (registered.has(openClawName)) continue;
      registered.add(openClawName);
      // IMPORTANT: pass `name` in the options object. When the second arg
      // to registerTool is a factory (not a static tool), OpenClaw's
      // registry stores the entry with `names: []` and falls back to the
      // plugin's full `declaredNames` list (every name from
      // contracts.tools) at lookup time. With every entry matching every
      // declared name, the tool-execution lookup's `Array.find(...)` just
      // returns the FIRST registered entry, whose factory produces the
      // wrong tool → "plugin tool runtime missing". Setting `opts.name`
      // pins each entry to one specific tool name so lookup picks the
      // right factory.
      api.registerTool(
        (ctx: ToolContext) => ({
          name: openClawName,
          description: tool.description,
          // OpenClaw types `parameters` as a TypeBox TSchema but only reads it
          // as JSON Schema. We pass the schema directly — pulling in
          // @sinclair/typebox would fail at runtime because directory-mode
          // `openclaw plugins install` skips npm install for plugin deps.
          parameters: tool.parameters as unknown as never,
          async execute(_id: string, params: Record<string, unknown>) {
            const toolParams = withContext(params as Record<string, unknown>, ctx);
            logToolCall(api, tool.name, toolParams);
            const result = await client.callTool(tool.name, toolParams, _id);
            return toOpenClawToolResult(result);
          },
        }),
        { name: openClawName, ...(cfg.optional ? { optional: true } : {}) },
      );
    }

    // HTTP routes only in full mode — they bind to the live gateway HTTP
    // server. Discovery loads happen out of band and have no live server.
    if (mode === "full" && typeof api.registerHttpRoute === "function") {
      registerDataclawFrontendRoutes(api as Record<string, unknown> & {
        registerHttpRoute: (route: unknown) => void;
      });
    }
  },
};

function extractFromSessionKey(key: string): string | undefined {
  // OpenClaw 2026.5 routes Dataclaw chats through a channel-kind peer, so the
  // sessionKey shape is `agent:<agentId>:dataclaw:channel:<chat_id>`. Older
  // builds used `:explicit:<chat_id>`; accept both so re-installs of existing
  // chats keep working. Strip an optional thread suffix the agent runner may
  // append for forked subsessions.
  for (const marker of [":dataclaw:channel:", ":explicit:"]) {
    const idx = key.indexOf(marker);
    if (idx < 0) continue;
    const tail = key.slice(idx + marker.length);
    const threadIdx = tail.indexOf(":thread:");
    return threadIdx >= 0 ? tail.slice(0, threadIdx) : tail;
  }
  return undefined;
}

function withContext(params: Record<string, unknown>, ctx: ToolContext): Record<string, unknown> {
  const next = { ...params };

  // Dataclaw indexes datasets/plans/notebooks by the dataclaw chat id (the
  // uuid the user sees in the URL). That id is embedded in the OpenClaw
  // sessionKey — `agent:<agentId>:dataclaw:channel:<chat_id>` — NOT in
  // ctx.sessionId, which is OpenClaw's own per-session-record uuid (a
  // different value, regenerated on /new and /reset). Always try sessionKey
  // first; only fall back to sessionId for plugins/contexts that don't shape
  // a routable sessionKey.
  let rawSessionId: string | undefined;
  if (hasString(ctx.sessionKey)) {
    rawSessionId = extractFromSessionKey(ctx.sessionKey);
  }
  if (!rawSessionId && hasString(ctx.sessionId)) {
    rawSessionId = extractFromSessionKey(ctx.sessionId) ?? ctx.sessionId;
  }

  if (!hasString(next.session_id) && !hasString(next.titan_session_id) && !hasString(next.dataclaw_session_id) && rawSessionId) {
    next.session_id = rawSessionId;
    next.titan_session_id = rawSessionId;
  }
  if (!hasString(next.openclaw_session_key) && hasString(ctx.sessionKey)) {
    next.openclaw_session_key = ctx.sessionKey;
  }
  if (!hasString(next.openclaw_agent_id) && hasString(ctx.agentId)) {
    next.openclaw_agent_id = ctx.agentId;
  }
  return next;
}

function logToolCall(
  api: { logger?: { info?: (m: string) => void } },
  toolName: string,
  params: Record<string, unknown>,
): void {
  const msg =
    `[dataclaw] tool ${toolName}: ` +
    `sessionId=${stringOrEmpty(params.titan_session_id)} ` +
    `sessionKey=${stringOrEmpty(params.openclaw_session_key)} ` +
    `agentId=${stringOrEmpty(params.openclaw_agent_id)}`;
  if (typeof api.logger?.info === "function") api.logger.info(msg);
  else console.log(msg);
}

function hasString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function stringOrEmpty(value: unknown): string {
  return typeof value === "string" ? value : "";
}
