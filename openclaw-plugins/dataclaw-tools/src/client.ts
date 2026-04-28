import type { DataclawToolCallResponse, DataclawToolDefinition, DataclawToolsConfig } from "./types.js";

export function createDataclawToolsClient(config: DataclawToolsConfig) {
  const baseUrl = config.baseUrl.replace(/\/+$/, "");

  return {
    /**
     * Fetch the tool list from Dataclaw's GET /tools endpoint.
     * This replaces the static tool manifest — tools are discovered dynamically.
     */
    async listTools(): Promise<DataclawToolDefinition[]> {
      const response = await fetch(`${baseUrl}/api/tools`, {
        headers: authHeaders(config),
      });
      if (!response.ok) {
        throw new Error(`Dataclaw tools discovery failed: ${response.status}`);
      }
      const body = await response.json();
      // Dataclaw returns a flat array of tool definitions
      return Array.isArray(body) ? body : (body.tools ?? []);
    },

    /**
     * Call a tool on Dataclaw's POST /tools/{name}/call endpoint.
     */
    async callTool(toolName: string, params: Record<string, unknown>): Promise<unknown> {
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
      return body.result;
    },
  };
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
