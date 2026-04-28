import {
  createChannelPluginBase,
  createChatChannelPlugin,
} from "openclaw/plugin-sdk/channel-core";
import type { OpenClawConfig } from "openclaw/plugin-sdk/channel-core";
import { resolveDataclawFrontendAccount } from "./config.js";
import { responseBroker } from "./response-broker.js";
import { CHANNEL_ID, type DataclawFrontendAccount } from "./types.js";

/** POST a message to Dataclaw's API for persistence (fire-and-forget). */
async function pushToDataclawApi(
  sessionId: string,
  messageId: string,
  content: string,
): Promise<void> {
  const account = resolveDataclawFrontendAccount({});
  const apiUrl = account.dataclawApiUrl;
  if (!apiUrl) return;

  const url = `${apiUrl.replace(/\/+$/, "")}/api/chat/sessions/${encodeURIComponent(sessionId)}/message`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (account.token) headers["X-Dataclaw-Token"] = account.token;

  try {
    await fetch(url, {
      method: "POST", headers,
      body: JSON.stringify({ role: "assistant", content, messageId }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch { /* fire-and-forget */ }
}

function resolveTargetSession(params: Record<string, unknown>): string {
  const target = params.to ?? params.target ?? params.conversationId ?? params.channelId ?? params.sessionId;
  if (typeof target !== "string" || target.trim() === "") {
    throw new Error("dataclaw-frontend: outbound message missing target session id");
  }
  return target;
}

const builtPlugin = createChatChannelPlugin<DataclawFrontendAccount>({
  base: createChannelPluginBase({
    id: CHANNEL_ID,
    setup: {
      resolveAccount(cfg: OpenClawConfig, accountId?: string | null) {
        return resolveDataclawFrontendAccount(cfg, accountId);
      },
      inspectAccount() { return { enabled: true, configured: true, tokenStatus: "available" }; },
    },
  }),

  security: {
    dm: {
      channelKey: CHANNEL_ID,
      resolvePolicy: (account) => account.dmPolicy,
      resolveAllowFrom: (account) => account.allowFrom,
      defaultPolicy: "allowlist",
    },
  },

  threading: { topLevelReplyToMode: "reply" },

  messaging: {
    resolveSessionConversation(rawId: string) {
      const [baseConversationId, threadId] = rawId.split(":thread:", 2);
      return {
        conversationId: baseConversationId,
        baseConversationId,
        threadId,
        parentConversationCandidates: threadId ? [baseConversationId] : [],
      };
    },
  },

  outbound: {
    attachedResults: {
      sendText: async (params: Record<string, unknown>) => {
        const sessionId = resolveTargetSession(params);
        const text = typeof params.text === "string" ? params.text : "";
        const messageId = `dc-out-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        responseBroker.publish({ sessionId, text, messageId, type: "message", createdAt: new Date().toISOString() });
        return { messageId };
      },
      sendPayload: async (params: Record<string, unknown>) => {
        const sessionId = resolveTargetSession(params);
        const text = typeof params.text === "string" ? params.text : JSON.stringify(params.payload);
        const messageId = `dc-out-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        responseBroker.publish({
          sessionId, text, messageId, type: "message", createdAt: new Date().toISOString(),
          metadata: params.payload as Record<string, unknown>,
        });
        return { messageId };
      },
    },
  },

  actions: {
    describeMessageTool() { return { actions: ["send", "edit"], capabilities: [] }; },
    supportsAction({ action }) { return action === "send" || action === "edit"; },
    async handleAction(ctx) {
      if (ctx.action !== "edit") return null;
      const messageId = String(ctx.params.messageId ?? "").trim();
      const text = String(ctx.params.message ?? ctx.params.text ?? "").trim();
      const sessionId = resolveTargetSession(ctx.params as Record<string, unknown>);
      if (!messageId) throw new Error("dataclaw-frontend edit requires messageId");
      if (!text) throw new Error("dataclaw-frontend edit requires text");

      responseBroker.publish({ sessionId, text, messageId, type: "edit", createdAt: new Date().toISOString() });
      void pushToDataclawApi(sessionId, messageId, text);

      return {
        content: [{ type: "text", text: JSON.stringify({ ok: true, messageId }) }],
        details: { ok: true, channel: CHANNEL_ID, action: "edit", messageId },
      };
    },
  },
});

export const dataclawFrontendPlugin = {
  ...builtPlugin,
  config: {
    ...(builtPlugin as Record<string, unknown>).config,
    listAccountIds(cfg: any): string[] {
      const section = cfg?.channels?.[CHANNEL_ID];
      const accounts = section?.accounts ? Object.keys(section.accounts) : [];
      return accounts.length > 0 ? accounts : ["default"];
    },
    resolveAccount(cfg: any, accountId?: string | null) {
      return resolveDataclawFrontendAccount(cfg, accountId);
    },
    inspectAccount(_cfg: any, _accountId?: string | null) {
      return { enabled: true, configured: true, tokenStatus: "available" };
    },
    isEnabled(cfg: any, accountId?: string | null): boolean {
      return resolveDataclawFrontendAccount(cfg, accountId).enabled;
    },
    isConfigured(cfg: any, accountId?: string | null): boolean {
      return resolveDataclawFrontendAccount(cfg, accountId).enabled;
    },
  },
};
