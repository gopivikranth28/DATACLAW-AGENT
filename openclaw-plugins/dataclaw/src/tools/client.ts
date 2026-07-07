import type { DataclawToolCallResponse, DataclawToolsConfig } from "./types.js";

export function createDataclawToolsClient(config: DataclawToolsConfig) {
  const baseUrl = config.baseUrl.replace(/\/+$/, "");

  return {
    /**
     * Call a tool on Dataclaw's POST /tools/{name}/call endpoint.
     */
    async callTool(toolName: string, params: Record<string, unknown>, toolCallId?: string): Promise<unknown> {
      const { toolParams, sessionId, sessionKey, agentId } = splitContextParams(params);
      const response = await fetch(`${baseUrl}/api/tools/${encodeURIComponent(toolName)}/call`, {
        method: "POST",
        headers: {
          ...authHeaders(config),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          params: toolParams,
          session_id: sessionId,
          titan_session_id: sessionId,       // backward-compat key name
          openclaw_session_key: sessionKey,
          openclaw_agent_id: agentId,
        }),
      });
      const body = await readJson<DataclawToolCallResponse>(response);
      if (!response.ok || !body.ok) {
        throw new Error(`Dataclaw tool ${toolName} failed: ${response.status} ${JSON.stringify(body)}`);
      }
      const result = body.result;
      if (sessionId) {
        await persistToolCall(config, baseUrl, {
          sessionId,
          toolName,
          toolCallId: toolCallId || `oc-${Date.now()}-${Math.random().toString(36).slice(2)}`,
          args: toolParams,
          result,
        });
      }
      return result;
    },
  };
}

async function persistToolCall(
  config: DataclawToolsConfig,
  baseUrl: string,
  entry: {
    sessionId: string;
    toolName: string;
    toolCallId: string;
    args: Record<string, unknown>;
    result: unknown;
  },
): Promise<void> {
  try {
    const response = await fetch(`${baseUrl}/api/chat/sessions/${encodeURIComponent(entry.sessionId)}/message`, {
      method: "POST",
      headers: {
        ...authHeaders(config),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        role: "tool_call",
        messageId: `tc-${entry.toolCallId}`,
        toolCallId: entry.toolCallId,
        toolName: entry.toolName,
        args: entry.args,
        result: entry.result,
        status: "complete",
      }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) {
      console.warn(`[dataclaw] tool-call persist failed for ${entry.toolName}: ${response.status}`);
    }
  } catch (error) {
    console.warn(`[dataclaw] tool-call persist error for ${entry.toolName}: ${error}`);
  }
}

function splitContextParams(params: Record<string, unknown>): {
  toolParams: Record<string, unknown>;
  sessionId?: string;
  sessionKey?: string;
  agentId?: string;
} {
  const toolParams = { ...params };
  const sessionId = takeString(toolParams, "session_id") ?? takeString(toolParams, "titan_session_id") ?? takeString(toolParams, "dataclaw_session_id");
  const sessionKey = takeString(toolParams, "openclaw_session_key");
  const agentId = takeString(toolParams, "openclaw_agent_id");
  return { toolParams, sessionId, sessionKey, agentId };
}

function takeString(params: Record<string, unknown>, key: string): string | undefined {
  const value = params[key];
  delete params[key];
  return typeof value === "string" && value.trim() ? value : undefined;
}

function authHeaders(config: DataclawToolsConfig): Record<string, string> {
  return config.token
    ? { Authorization: `Bearer ${config.token}`, "X-Dataclaw-Token": config.token }
    : {};
}

async function readJson<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text) return {} as T;
  try { return JSON.parse(text) as T; }
  catch { return { error: text } as T; }
}
