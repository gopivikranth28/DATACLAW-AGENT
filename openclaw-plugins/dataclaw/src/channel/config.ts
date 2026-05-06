import {
  CHANNEL_ID,
  DEFAULT_ACCOUNT_ID,
  type OpenClawConfigLike,
  type DataclawFrontendAccount,
} from "./types.js";

const DEFAULT_RESPONSE_TIMEOUT_MS = 30_000;

type DataclawFrontendConfig = {
  enabled?: boolean;
  token?: string;
  dataclawApiUrl?: string;
  allowFrom?: string[];
  dmSecurity?: string;
  responseTimeoutMs?: number;
  accounts?: Record<string, Omit<DataclawFrontendConfig, "accounts">>;
};

export function resolveDataclawFrontendAccount(
  cfg: OpenClawConfigLike,
  accountId?: string | null,
): DataclawFrontendAccount {
  const accountKey = accountId ?? DEFAULT_ACCOUNT_ID;
  const section = resolveAccountSection(cfg, accountKey);
  // All config reads come from cfg.channels.dataclaw.* — never from
  // environment variables. The 2026.5 install scanner blocks any plugin
  // that mixes env-var reads with outbound HTTP, which the structured-
  // config approach avoids. The install service writes these values to
  // channels.dataclaw.* directly.
  return {
    accountId: accountKey,
    enabled: section.enabled !== false,
    token: section.token,
    dataclawApiUrl: section.dataclawApiUrl,
    allowFrom: Array.isArray(section.allowFrom) ? section.allowFrom : [],
    dmPolicy: section.dmSecurity,
    responseTimeoutMs:
      typeof section.responseTimeoutMs === "number"
        ? section.responseTimeoutMs
        : DEFAULT_RESPONSE_TIMEOUT_MS,
  };
}

function resolveSection(cfg: OpenClawConfigLike): DataclawFrontendConfig {
  const section = cfg.channels?.[CHANNEL_ID];
  if (!section || typeof section !== "object") return {};
  return section as DataclawFrontendConfig;
}

function resolveAccountSection(
  cfg: OpenClawConfigLike,
  accountId: string,
): DataclawFrontendConfig {
  const section = resolveSection(cfg);
  const account = section.accounts?.[accountId];
  const { accounts: _accounts, ...topLevel } = section;
  return account ? { ...topLevel, ...account } : topLevel;
}
