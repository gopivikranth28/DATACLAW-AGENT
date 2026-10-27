import {
  defineChannelPluginEntry,
  type OpenClawPluginApi,
} from "openclaw/plugin-sdk/channel-core";
import type { AnyAgentTool, OpenClawPluginToolContext } from "openclaw/plugin-sdk/core";
import { dataclawFrontendPlugin } from "./src/channel/channel.js";
import { registerDataclawFrontendRoutes } from "./src/channel/http-routes.js";
import { createDataclawToolsClient } from "./src/tools/client.js";
import { resolveDataclawToolsConfig } from "./src/tools/config.js";
import { DATACLAW_TOOL_MANIFEST } from "./src/tools/tool-manifest.js";
import { toOpenClawToolResult } from "./src/tools/tool-result.js";

/**
 * `defineChannelPluginEntry` registers the channel in every runtime mode and
 * calls `registerFull` in both "full" and "tool-discovery" mode. The latter is
 * the scoped load OpenClaw uses to resolve plugin tools at execution time, so
 * the tool factories must be registered from `registerFull`. HTTP routes bind
 * to the live gateway server and are registered in "full" mode only.
 */
export default defineChannelPluginEntry({
  id: "dataclaw",
  name: "Dataclaw",
  description:
    "Dataclaw integration: registers Python tools and routes UI messages between Dataclaw and OpenClaw.",
  plugin: dataclawFrontendPlugin,
  registerFull(api) {
    registerDataclawTools(api);
    if (api.registrationMode === "full") registerDataclawFrontendRoutes(api);
  },
});

function registerDataclawTools(api: OpenClawPluginApi): void {
  // Prefix/optional come from plugins.entries.dataclaw.config and only matter
  // at registration. Connection settings (URL, token) are re-read on every
  // call so a `config set channels.dataclaw.*` hot reload takes effect.
  const { prefix, optional } = resolveDataclawToolsConfig(api.config, api.pluginConfig);
  const registered = new Set<string>();
  for (const tool of DATACLAW_TOOL_MANIFEST) {
    const openClawName = `${prefix}${tool.name}`;
    if (registered.has(openClawName)) continue;
    registered.add(openClawName);
    // Pass `name` in the options object so each factory is pinned to one
    // tool name. Without it the registry falls back to every name in
    // contracts.tools for each factory and tool lookup can pick the wrong one.
    api.registerTool(
      (ctx: OpenClawPluginToolContext): AnyAgentTool => ({
        name: openClawName,
        label: openClawName,
        description: tool.description,
        // The SDK types `parameters` as a TypeBox TSchema but only reads it as
        // JSON Schema, which is what the Dataclaw manifest provides. Pulling in
        // TypeBox just to wrap it would add a runtime dependency to the bundle.
        parameters: tool.parameters as unknown as AnyAgentTool["parameters"],
        async execute(toolCallId, params) {
          const toolParams = withContext((params ?? {}) as Record<string, unknown>, ctx);
          logToolCall(api, tool.name, toolParams);
          const cfg = resolveDataclawToolsConfig(api.runtime.config.current(), api.pluginConfig);
          const result = await createDataclawToolsClient(cfg).callTool(tool.name, toolParams, toolCallId);
          return toOpenClawToolResult(result);
        },
      }),
      { name: openClawName, ...(optional ? { optional: true } : {}) },
    );
  }
}

function extractFromSessionKey(key: string): string | undefined {
  // Dataclaw chats route through a channel-kind peer, so the sessionKey shape
  // is `agent:<agentId>:dataclaw:channel:<chat_id>`. Pre-2026.5 builds used
  // `:explicit:<chat_id>`; accept both so existing chats keep working. Strip
  // an optional thread suffix the agent runner may append for forked
  // subsessions.
  for (const marker of [":dataclaw:channel:", ":explicit:"]) {
    const idx = key.indexOf(marker);
    if (idx < 0) continue;
    const tail = key.slice(idx + marker.length);
    const threadIdx = tail.indexOf(":thread:");
    return threadIdx >= 0 ? tail.slice(0, threadIdx) : tail;
  }
  return undefined;
}

function withContext(params: Record<string, unknown>, ctx: OpenClawPluginToolContext): Record<string, unknown> {
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

function logToolCall(api: OpenClawPluginApi, toolName: string, params: Record<string, unknown>): void {
  api.logger.info(
    `[dataclaw] tool ${toolName}: ` +
    `sessionId=${stringOrEmpty(params.titan_session_id)} ` +
    `sessionKey=${stringOrEmpty(params.openclaw_session_key)} ` +
    `agentId=${stringOrEmpty(params.openclaw_agent_id)}`,
  );
}

function hasString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function stringOrEmpty(value: unknown): string {
  return typeof value === "string" ? value : "";
}
