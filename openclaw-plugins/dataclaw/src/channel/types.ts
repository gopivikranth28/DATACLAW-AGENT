export const CHANNEL_ID = "dataclaw";
export const DEFAULT_ACCOUNT_ID = "default";

export type DataclawFrontendAccount = {
  accountId: string | null;
  enabled: boolean;
  token?: string;
  dataclawApiUrl?: string;
  allowFrom: string[];
  dmPolicy?: string;
  responseTimeoutMs: number;
};

export type DataclawInboundMessage = {
  sessionId: string;
  projectId?: string;
  workspaceId?: string;
  userId: string;
  text: string;
  messageId?: string;
  metadata?: Record<string, unknown>;
};

export type DataclawOutboundMessage = {
  sessionId: string;
  text: string;
  messageId: string;
  createdAt: string;
  type?: "message" | "edit";
  metadata?: Record<string, unknown>;
};

/**
 * The slice of OpenClaw config the channel reads. Structural so both the SDK's
 * `OpenClawConfig` and the DeepReadonly `runtime.config.current()` view fit.
 */
export type OpenClawConfigLike = {
  channels?: object;
};
