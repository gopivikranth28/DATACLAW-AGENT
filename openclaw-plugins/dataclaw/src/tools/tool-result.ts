import type { AnyAgentTool } from "openclaw/plugin-sdk/core";

type ToolResult = Awaited<ReturnType<AnyAgentTool["execute"]>>;

export function toOpenClawToolResult(result: unknown): ToolResult {
  const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
  return {
    content: [{ type: "text", text }],
    details: result,
  };
}
