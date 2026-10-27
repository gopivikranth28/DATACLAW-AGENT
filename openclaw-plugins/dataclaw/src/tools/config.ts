import type { DataclawToolsConfig } from "./types.js";

const DEFAULT_BASE_URL = "http://localhost:8000";
const DEFAULT_PREFIX = "dataclaw_";
const PLUGIN_ID = "dataclaw";

type LooseConfig = { channels?: object } | undefined | null;

/**
 * Read tools-side runtime config out of OpenClaw config. Connection settings
 * (token, base URL) live with the channel under `channels.dataclaw.*` because
 * a Dataclaw chat is the channel's authentication/transport surface. Tools-
 * only knobs (registration prefix, optional-tool failure mode) live in the
 * per-plugin namespace `plugins.entries.dataclaw.config.*`, validated by the
 * manifest's top-level `configSchema`.
 *
 * Config is read exclusively from OpenClaw's structured config — never from
 * environment variables. The install service writes both surfaces directly.
 *
 * `pluginConfig` is `api.pluginConfig` (the host's already-resolved
 * `plugins.entries.dataclaw.config`); the channel section comes from the
 * full config so connection changes are picked up per call.
 */
export function resolveDataclawToolsConfig(
  cfg: LooseConfig,
  pluginConfig: Record<string, unknown> = {},
): DataclawToolsConfig {
  const channelSection = (cfg?.channels as Record<string, unknown> | undefined)?.[PLUGIN_ID];
  const channel = channelSection && typeof channelSection === "object"
    ? (channelSection as Record<string, unknown>)
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
