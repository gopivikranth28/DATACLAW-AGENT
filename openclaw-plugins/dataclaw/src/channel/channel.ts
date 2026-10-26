import {
  createChannelPluginBase,
  createChatChannelPlugin,
  type ChannelPlugin,
  type OpenClawConfig,
} from "openclaw/plugin-sdk/channel-core";
import type {
  ChannelMessageActionAdapter,
  ChannelOutboundContext,
} from "openclaw/plugin-sdk/channel-contract";
import { resolveDataclawFrontendAccount } from "./config.js";
import { responseBroker } from "./response-broker.js";
import { CHANNEL_ID, DEFAULT_ACCOUNT_ID, type DataclawFrontendAccount } from "./types.js";

/** POST a message to Dataclaw's API for persistence (fire-and-forget). */
async function pushToDataclawApi(
  cfg: OpenClawConfig,
  sessionId: string,
  messageId: string,
  content: string,
): Promise<void> {
  const account = resolveDataclawFrontendAccount(cfg);
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
    throw new Error("dataclaw: outbound message missing target session id");
  }
  return target;
}

function newOutboundMessageId(): string {
  return `dc-out-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Outbound sends just fan out to whoever is listening on /dataclaw/events. */
function publishOutbound(ctx: ChannelOutboundContext, text: string, metadata?: Record<string, unknown>) {
  const messageId = newOutboundMessageId();
  responseBroker.publish({
    sessionId: resolveTargetSession(ctx), text, messageId, type: "message",
    createdAt: new Date().toISOString(), metadata,
  });
  return { messageId };
}

const configAdapter: ChannelPlugin<DataclawFrontendAccount>["config"] = {
  listAccountIds(cfg) {
    const section = (cfg.channels as Record<string, { accounts?: Record<string, unknown> }> | undefined)?.[CHANNEL_ID];
    const accounts = section?.accounts ? Object.keys(section.accounts) : [];
    return accounts.length > 0 ? accounts : [DEFAULT_ACCOUNT_ID];
  },
  resolveAccount: (cfg, accountId) => resolveDataclawFrontendAccount(cfg, accountId),
  inspectAccount(cfg, accountId) {
    const account = resolveDataclawFrontendAccount(cfg, accountId);
    return {
      enabled: account.enabled,
      configured: true,
      tokenStatus: account.token ? "available" : "missing",
    };
  },
  isEnabled: (account) => account.enabled,
  // The channel has no required credential: an unset token just disables the
  // X-Dataclaw-Token check, which is what the local bundled install relies on.
  isConfigured: () => true,
};

const actionsAdapter: ChannelMessageActionAdapter = {
  describeMessageTool: () => ({ actions: ["send", "edit"], capabilities: [] }),
  // Only "edit" is plugin-owned. Reporting "send" as unsupported routes it
  // through the canonical outbound adapter (sendText/sendPayload) below.
  supportsAction: ({ action }) => action === "edit",
  async handleAction(ctx) {
    if (ctx.action !== "edit") throw new Error(`dataclaw: unsupported message action ${ctx.action}`);
    const messageId = String(ctx.params.messageId ?? "").trim();
    const text = String(ctx.params.message ?? ctx.params.text ?? "").trim();
    const sessionId = resolveTargetSession(ctx.params);
    if (!messageId) throw new Error("dataclaw edit requires messageId");
    if (!text) throw new Error("dataclaw edit requires text");

    responseBroker.publish({ sessionId, text, messageId, type: "edit", createdAt: new Date().toISOString() });
    void pushToDataclawApi(ctx.cfg, sessionId, messageId, text);

    return {
      content: [{ type: "text", text: JSON.stringify({ ok: true, messageId }) }],
      details: { ok: true, channel: CHANNEL_ID, action: "edit", messageId },
    };
  },
};

const builtPlugin = createChatChannelPlugin<DataclawFrontendAccount>({
  base: {
    ...createChannelPluginBase<DataclawFrontendAccount>({
      id: CHANNEL_ID,
      meta: {
        label: "Dataclaw",
        selectionLabel: "Dataclaw",
        // The host's default for a channel without docs; set explicitly so it
        // doesn't warn "registered incomplete metadata" on every reload.
        docsPath: "/channels/dataclaw",
        blurb: "Connect OpenClaw to the Dataclaw web frontend.",
      },
    }),
    // createChannelPluginBase types `config` as optional; the chat-plugin
    // builder needs it present, so set it on the composed base directly.
    config: configAdapter,
    messaging: {
      resolveSessionConversation({ rawId }) {
        const [baseConversationId, threadId] = rawId.split(":thread:", 2);
        return {
          id: baseConversationId,
          threadId: threadId ?? null,
          baseConversationId,
          parentConversationCandidates: threadId ? [baseConversationId] : [],
        };
      },
      inferTargetChatType: () => "channel",
      targetResolver: {
        hint: "Provide the dataclaw chat session id (uuid).",
        // Any non-empty string is a valid dataclaw chat target — there's no
        // separate directory to look up. Without this, host directory lookup
        // throws unknownTargetError for bare UUID chat ids.
        looksLikeId: (raw, normalized) => Boolean((normalized ?? raw).trim()),
        resolveTarget: async ({ input, normalized }) => {
          const to = (normalized ?? input).trim();
          if (!to) return null;
          return { to, kind: "channel", source: "normalized" };
        },
      },
    },
    actions: actionsAdapter,
  },

  security: {
    dm: {
      channelKey: CHANNEL_ID,
      resolvePolicy: (account) => account.dmPolicy,
      resolveAllowFrom: (account) => account.allowFrom,
      defaultPolicy: "allowlist",
    },
  },

  threading: { topLevelReplyToMode: "reply" },

  outbound: {
    base: {
      deliveryMode: "direct",
      async sendPayload(ctx) {
        const text = ctx.payload.text || ctx.text || JSON.stringify(ctx.payload);
        return {
          channel: CHANNEL_ID,
          ...publishOutbound(ctx, text, { payload: ctx.payload as unknown as Record<string, unknown> }),
        };
      },
    },
    attachedResults: {
      channel: CHANNEL_ID,
      sendText: (ctx) => publishOutbound(ctx, ctx.text),
    },
  },
});

export const dataclawFrontendPlugin: ChannelPlugin<DataclawFrontendAccount> = builtPlugin;
