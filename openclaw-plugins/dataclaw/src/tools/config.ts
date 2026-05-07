import type { DataclawToolsConfig } from "./types.js";

const DEFAULT_BASE_URL = "http://localhost:8000";
const DEFAULT_PREFIX = "dataclaw_";
const PLUGIN_ID = "dataclaw";

type LooseConfig =
  | {
      channels?: Record<string, unknown>;
      plugins?: { entries?: Record<string, unknown> };
    }
  | undefined
  | null;

/**
 * Read tools-side runtime config out of OpenClaw config. Connection settings
 * (token, base URL) live with the channel under `channels.dataclaw.*` because
 * a Dataclaw chat is the channel's authentication/transport surface. Tools-
 * only knobs (registration prefix, optional-tool failure mode) live in the
 * per-plugin namespace `plugins.entries.dataclaw.config.*`, validated by the
 * manifest's top-level `configSchema`.
 *
 * Config is read exclusively from OpenClaw's structured config — never from
 * environment variables. The 2026.5 install scanner blocks any plugin that
 * mixes env-var reads with outbound HTTP, which this approach avoids. The
 * install service writes both surfaces directly.
 */
export function resolveDataclawToolsConfig(cfg: LooseConfig): DataclawToolsConfig {
  const channelSection = cfg?.channels?.[PLUGIN_ID];
  const channel = channelSection && typeof channelSection === "object"
    ? (channelSection as Record<string, unknown>)
    : {};
  const pluginEntry = cfg?.plugins?.entries?.[PLUGIN_ID];
  const pluginConfig = pluginEntry && typeof pluginEntry === "object"
    ? ((pluginEntry as Record<string, unknown>).config as Record<string, unknown> | undefined) ?? {}
    : {};

  const baseUrl = typeof channel.dataclawApiUrl === "string" && channel.dataclawApiUrl.trim()
    ? (channel.dataclawApiUrl as string)
    : DEFAULT_BASE_URL;
  const token = typeof channel.token === "string" && channel.token.trim()
    ? (channel.token as string)
    : undefined;
  const prefix = typeof pluginConfig.toolsPrefix === "string" && pluginConfig.toolsPrefix.trim()
    ? (pluginConfig.toolsPrefix as string)
    : DEFAULT_PREFIX;
  const optional = pluginConfig.toolsOptional === true
    || pluginConfig.toolsOptional === "true"
    || pluginConfig.toolsOptional === "1";
  return { baseUrl, token, optional, prefix };
}
