import type { DataclawToolsConfig } from "./types.js";

const DEFAULT_BASE_URL = "http://localhost:8000";
const DEFAULT_PREFIX = "dataclaw_";

export function resolveDataclawToolsConfig(): DataclawToolsConfig {
  const optionalValue = process.env.DATACLAW_TOOLS_OPTIONAL;
  return {
    baseUrl: process.env.DATACLAW_API_URL ?? DEFAULT_BASE_URL,
    token: process.env.DATACLAW_TOOLS_TOKEN,
    optional: optionalValue === "true" || optionalValue === "1",
    prefix: process.env.DATACLAW_TOOLS_PREFIX ?? DEFAULT_PREFIX,
  };
}
