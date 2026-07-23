import { resolveDataclawFrontendAccount } from "./config.js";
import { responseBroker } from "./response-broker.js";
import { CHANNEL_ID, DEFAULT_ACCOUNT_ID, type OpenClawConfigLike, type DataclawInboundMessage } from "./types.js";

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
    if (!resp.ok) console.warn(`[dataclaw] persist failed: ${resp.status}`);
  } catch (err) {
    console.warn(`[dataclaw] persist error: ${err}`);
  }
}

type InboundContext = {
  Body: string; RawBody: string; CommandBody: string; CommandAuthorized: boolean;
  From: string; To: string; SessionKey: string; AccountId: string;
  ChatType: "direct"; ConversationLabel: string; SenderName: string; SenderId: string;
  Provider: typeof CHANNEL_ID; Surface: typeof CHANNEL_ID;
  OriginatingChannel: typeof CHANNEL_ID; OriginatingTo: string;
  MessageSid: string; Timestamp: number;
  ProjectId?: string; WorkspaceId?: string;
};

export async function dispatchDataclawFrontendInbound(
  api: RuntimeApi,
  cfg: OpenClawConfigLike,
  message: DataclawInboundMessage,
): Promise<void> {
  const runtime = resolveRuntime(api);

  // Resolve the route with peer.kind: "channel" so the resulting sessionKey is
  // per-chat (`agent:main:dataclaw:channel:<chat_id>`) and never collapses to
  // the agent's main session via the dmScope default.
  const route = runtime.channel.routing.resolveAgentRoute({
    cfg,
    channel: CHANNEL_ID,
    accountId: DEFAULT_ACCOUNT_ID,
    peer: { kind: "channel", id: message.sessionId },
  });

  const ctx = buildContext(message, route.sessionKey, route.accountId);

  const deliveredChunks: string[] = [];
  let lastMessageId = "";

  await runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher({
    ctx, cfg,
    dispatcherOptions: {
      deliver: async (payload: ReplyPayload) => {
        const hasMedia = Boolean(payload.mediaUrl || (payload.mediaUrls && payload.mediaUrls.length > 0));
        const text = [payload.text || (hasMedia ? "Visual output captured in Dataclaw artifacts. Open the App panel/report surface to view it." : "")]
          .filter(Boolean)
          .join("\n");
        if (!text) return;
        lastMessageId = `dc-out-${Date.now()}-${rand()}`;
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

function rand(): string {
  return Math.random().toString(36).slice(2);
}

function buildContext(message: DataclawInboundMessage, sessionKey: string, accountId: string): InboundContext {
  const messageId = message.messageId ?? `dc-in-${Date.now()}-${rand()}`;
  const dataclawInstructions = [
    "[Dataclaw runtime instructions]",
    "- Use Dataclaw tools as the source of truth for plans, notebooks, data work, visual reports, and files.",
    "- Before running notebooks, code, or data tools for analysis, call dataclaw_propose_plan unless the user explicitly asks for a quick/no-plan answer. If Dataclaw auto mode is active the plan tool will auto-approve; otherwise wait for approval before execution.",
    "- Keep notebook work visible by using notebook/cell execution tools rather than hiding work in final prose.",
    "- For analytical answers, build the in-app visual report with dataclaw_report_design_report (then dataclaw_report_publish); do not answer with raw media paths or OpenClaw canvas-pairing language.",
    "",
  ].join("\n");
  const scopedText = message.projectId
    ? `${dataclawInstructions}[Dataclaw project_id=${message.projectId} workspace_id=${message.workspaceId ?? message.projectId}]\n${message.text}`
    : `${dataclawInstructions}${message.text}`;
  return {
    Body: scopedText, RawBody: scopedText, CommandBody: scopedText, CommandAuthorized: true,
    From: message.userId, To: message.sessionId, SessionKey: sessionKey, AccountId: accountId,
    // ChatType: "direct" so the host's source-reply-delivery-mode resolver
    // picks "automatic" (channel/group default to message_tool_only since
    // OpenClaw 2026.4.27, which would suppress plain agent text). The
    // sessionKey is already per-chat from peer.kind: "channel" routing.
    ChatType: "direct", ConversationLabel: `Dataclaw ${message.sessionId}`,
    SenderName: message.userId, SenderId: message.userId,
    Provider: CHANNEL_ID, Surface: CHANNEL_ID,
    OriginatingChannel: CHANNEL_ID, OriginatingTo: message.sessionId,
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
    throw new Error("[dataclaw] Runtime missing required channel methods");
  }
  return {
    channel: {
      reply: { dispatchReplyWithBufferedBlockDispatcher: dispatch as (p: unknown) => Promise<void> },
      routing: { resolveAgentRoute: resolveAgentRoute as (p: unknown) => { sessionKey: string; accountId: string } },
    },
  };
}
