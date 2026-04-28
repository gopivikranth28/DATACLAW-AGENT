import { resolveDataclawFrontendAccount } from "./config.js";
import { responseBroker } from "./response-broker.js";
import type { OpenClawConfigLike, DataclawInboundMessage } from "./types.js";

type RuntimeApi = Record<string, unknown>;
type ReplyPayload = { text?: string; mediaUrl?: string; mediaUrls?: string[] };

async function persistToDataclawApi(
  cfg: OpenClawConfigLike,
  sessionId: string,
  text: string,
  messageId: string,
  accountId?: string,
): Promise<void> {
  const account = resolveDataclawFrontendAccount(cfg, accountId);
  const apiUrl = account.dataclawApiUrl;
  if (!apiUrl) return;

  const url = `${apiUrl.replace(/\/+$/, "")}/api/chat/sessions/${encodeURIComponent(sessionId)}/message`;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (account.token) headers["X-Dataclaw-Token"] = account.token;

  try {
    const resp = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify({ role: "assistant", content: text, messageId }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) console.warn(`[dataclaw-frontend] persist failed: ${resp.status}`);
  } catch (err) {
    console.warn(`[dataclaw-frontend] persist error: ${err}`);
  }
}

type InboundContext = {
  Body: string; RawBody: string; CommandBody: string; CommandAuthorized: boolean;
  From: string; To: string; SessionKey: string; AccountId: string;
  ChatType: "direct"; ConversationLabel: string; SenderName: string; SenderId: string;
  Provider: "dataclaw-frontend"; Surface: "dataclaw-frontend";
  OriginatingChannel: "dataclaw-frontend"; OriginatingTo: string;
  MessageSid: string; Timestamp: number;
  ProjectId?: string; WorkspaceId?: string;
};

export async function dispatchDataclawFrontendInbound(
  api: RuntimeApi,
  cfg: OpenClawConfigLike,
  message: DataclawInboundMessage,
): Promise<void> {
  const runtime = resolveRuntime(api);
  const route = runtime.channel.routing.resolveAgentRoute({
    cfg, channel: "dataclaw-frontend", accountId: "default",
    peer: { kind: "dm", id: message.sessionId },
  });
  const sessionKey = `agent:main:explicit:${safeName(message.sessionId)}`;
  const ctx = buildContext(message, sessionKey, route.accountId);

  const deliveredChunks: string[] = [];
  let lastMessageId = "";

  await runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher({
    ctx, cfg,
    dispatcherOptions: {
      deliver: async (payload: ReplyPayload) => {
        const text = [payload.text, payload.mediaUrl, ...(payload.mediaUrls ?? [])].filter(Boolean).join("\n");
        if (!text) return;
        lastMessageId = `dc-out-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        deliveredChunks.push(text);
        responseBroker.publish({
          sessionId: message.sessionId, text, messageId: lastMessageId,
          type: "message", createdAt: new Date().toISOString(),
          metadata: { accountId: route.accountId, sessionKey: route.sessionKey },
        });
      },
      onError: (error: unknown) => {
        lastMessageId = `dc-error-${Date.now()}`;
        const text = `OpenClaw error: ${error instanceof Error ? error.message : String(error)}`;
        deliveredChunks.push(text);
        responseBroker.publish({
          sessionId: message.sessionId, text, messageId: lastMessageId,
          type: "message", createdAt: new Date().toISOString(),
        });
      },
    },
  });

  if (deliveredChunks.length > 0) {
    void persistToDataclawApi(cfg, message.sessionId, deliveredChunks.join("\n\n"), lastMessageId, route.accountId);
  }
}

function safeName(sessionId: string): string {
  return sessionId.trim().replace(/[^a-zA-Z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 96) || "dataclaw-ui";
}

function buildContext(message: DataclawInboundMessage, sessionKey: string, accountId: string): InboundContext {
  const messageId = message.messageId ?? `dc-in-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const scopedText = message.projectId
    ? `[Dataclaw project_id=${message.projectId} workspace_id=${message.workspaceId ?? message.projectId}]\n${message.text}`
    : message.text;
  return {
    Body: scopedText, RawBody: scopedText, CommandBody: scopedText, CommandAuthorized: true,
    From: message.userId, To: message.sessionId, SessionKey: sessionKey, AccountId: accountId,
    ChatType: "direct", ConversationLabel: `Dataclaw ${message.sessionId}`,
    SenderName: message.userId, SenderId: message.userId,
    Provider: "dataclaw-frontend", Surface: "dataclaw-frontend",
    OriginatingChannel: "dataclaw-frontend", OriginatingTo: message.sessionId,
    MessageSid: messageId, Timestamp: Date.now(),
    ProjectId: message.projectId, WorkspaceId: message.workspaceId,
  };
}

function resolveRuntime(api: RuntimeApi) {
  const runtime = api.runtime as Record<string, unknown> | undefined;
  const channel = runtime?.channel as Record<string, unknown> | undefined;
  const reply = channel?.reply as Record<string, unknown> | undefined;
  const routing = channel?.routing as Record<string, unknown> | undefined;
  const dispatch = reply?.dispatchReplyWithBufferedBlockDispatcher;
  const resolveAgentRoute = routing?.resolveAgentRoute;
  if (typeof dispatch !== "function" || typeof resolveAgentRoute !== "function") {
    throw new Error("[dataclaw-frontend] Runtime missing required channel methods");
  }
  return {
    channel: {
      reply: { dispatchReplyWithBufferedBlockDispatcher: dispatch as (p: unknown) => Promise<void> },
      routing: { resolveAgentRoute: resolveAgentRoute as (p: unknown) => { sessionKey: string; accountId: string } },
    },
  };
}
