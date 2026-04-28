export const CHANNEL_ID = "dataclaw-frontend";
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

export type OpenClawConfigLike = {
  channels?: Record<string, unknown>;
};
