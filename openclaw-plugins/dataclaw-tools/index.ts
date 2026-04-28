import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { Type } from "@sinclair/typebox";
import { createDataclawToolsClient } from "./src/client.js";
import { resolveDataclawToolsConfig } from "./src/config.js";
import { DATACLAW_TOOL_MANIFEST } from "./src/tool-manifest.js";
import { toOpenClawToolResult } from "./src/tool-result.js";
import type { JsonSchema } from "./src/types.js";

type ToolContext = {
  sessionId?: string;
  sessionKey?: string;
  agentId?: string;
};

export default definePluginEntry({
  id: "dataclaw-tools",
  name: "Dataclaw Tools",
  description: "Expose Dataclaw Python tools to OpenClaw",
  register(api) {
    const cfg = resolveDataclawToolsConfig();
    const client = createDataclawToolsClient(cfg);
    const registered = new Set<string>();

    // Register every tool from the static manifest
    for (const tool of DATACLAW_TOOL_MANIFEST) {
      const openClawName = `${cfg.prefix}${tool.name}`;
      registerOnce(
        api,
        registered,
        openClawName,
        (ctx: ToolContext) => ({
          name: openClawName,
          description: `${tool.description}\n\nBacked by Dataclaw tool: ${tool.name}`,
          parameters: Type.Unsafe(tool.parameters as JsonSchema),
          async execute(_id: string, params: Record<string, unknown>) {
            const toolParams = withContext(params as Record<string, unknown>, ctx);
            logToolCall(api, tool.name, toolParams);
            const result = await client.callTool(tool.name, toolParams);
            return toOpenClawToolResult(result);
          },
        }),
        cfg.optional ? { optional: true } : undefined,
      );
    }
  },
});

function extractFromSessionKey(key: string): string | undefined {
  const marker = ":explicit:";
  const idx = key.indexOf(marker);
  if (idx >= 0) return key.slice(idx + marker.length);
  return undefined;
}

function withContext(params: Record<string, unknown>, ctx: ToolContext): Record<string, unknown> {
  const next = { ...params };

  // Resolve the raw Dataclaw session id from context
  let rawSessionId: string | undefined;
  if (hasString(ctx.sessionId)) {
    rawSessionId = extractFromSessionKey(ctx.sessionId) ?? ctx.sessionId;
  } else if (hasString(ctx.sessionKey)) {
    rawSessionId = extractFromSessionKey(ctx.sessionKey);
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

function logToolCall(api: Record<string, unknown>, toolName: string, params: Record<string, unknown>): void {
  const msg =
    `[dataclaw-tools] tool ${toolName}: ` +
    `sessionId=${stringOrEmpty(params.titan_session_id)} ` +
    `sessionKey=${stringOrEmpty(params.openclaw_session_key)} ` +
    `agentId=${stringOrEmpty(params.openclaw_agent_id)}`;
  const logger = api.logger as { info?: (m: string) => void } | undefined;
  if (typeof logger?.info === "function") logger.info(msg);
  else console.log(msg);
}

function hasString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function stringOrEmpty(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function registerOnce(
  api: { registerTool: (tool: unknown, options?: Record<string, unknown>) => void },
  registered: Set<string>,
  name: string,
  tool: unknown,
  options?: Record<string, unknown>,
) {
  if (registered.has(name)) return;
  registered.add(name);
  api.registerTool(tool, options);
}
