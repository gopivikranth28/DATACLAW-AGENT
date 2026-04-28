import type { IncomingMessage, ServerResponse } from "node:http";
import { resolveDataclawFrontendAccount } from "./config.js";
import { dispatchDataclawFrontendInbound } from "./inbound.js";
import { responseBroker } from "./response-broker.js";
import type { OpenClawConfigLike, DataclawInboundMessage } from "./types.js";

type RuntimeApi = {
  registerHttpRoute(route: {
    path: string; auth: string;
    handler: (req: IncomingMessage, res: ServerResponse) => Promise<boolean>;
  }): void;
} & Record<string, unknown>;

type MessageRequest = DataclawInboundMessage & { waitForResponseMs?: number };

export function registerDataclawFrontendRoutes(api: RuntimeApi): void {
  // POST /dataclaw-frontend/message — receive user message, dispatch to agent, return response
  api.registerHttpRoute({
    path: "/dataclaw-frontend/message",
    auth: "plugin",
    handler: async (req, res) => {
      try {
        const cfg = await resolveConfig(api);
        const account = resolveDataclawFrontendAccount(cfg);
        assertAuthorized(req, account.token);

        const body = await readJson<MessageRequest>(req);
        validateMessage(body);

        const waitMs = typeof body.waitForResponseMs === "number" ? body.waitForResponseMs : account.responseTimeoutMs;
        const waitForResponse = waitMs > 0 ? responseBroker.waitForFinal(body.sessionId, waitMs) : Promise.resolve(null);

        await dispatchDataclawFrontendInbound(api, cfg, body);
        const response = await waitForResponse;

        writeJson(res, 200, { ok: true, sessionId: body.sessionId, response, timedOut: !response });
      } catch (error) {
        writeJson(res, statusForError(error), { ok: false, error: error instanceof Error ? error.message : String(error) });
      }
      return true;
    },
  });

  // GET /dataclaw-frontend/events — SSE stream for background responses
  api.registerHttpRoute({
    path: "/dataclaw-frontend/events",
    auth: "plugin",
    handler: async (req, res) => {
      try {
        const cfg = await resolveConfig(api);
        const account = resolveDataclawFrontendAccount(cfg);
        assertAuthorized(req, account.token);

        const sessionId = new URL(req.url ?? "", "http://localhost").searchParams.get("sessionId");
        if (!sessionId) throw badRequest("sessionId query parameter is required");

        res.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache", Connection: "keep-alive" });
        res.write("event: ready\ndata: {}\n\n");

        const unsubscribe = responseBroker.subscribe(sessionId, (message) => {
          res.write(`data: ${JSON.stringify(message)}\n\n`);
        });
        req.on("close", unsubscribe);
      } catch (error) {
        writeJson(res, statusForError(error), { ok: false, error: error instanceof Error ? error.message : String(error) });
      }
      return true;
    },
  });

  // GET /dataclaw-frontend/health
  api.registerHttpRoute({
    path: "/dataclaw-frontend/health",
    auth: "plugin",
    handler: async (_req, res) => {
      writeJson(res, 200, { ok: true, channel: "dataclaw-frontend" });
      return true;
    },
  });
}

function validateMessage(body: Partial<MessageRequest>): asserts body is MessageRequest {
  if (!body || typeof body !== "object") throw badRequest("JSON body required");
  if (!body.sessionId || typeof body.sessionId !== "string") throw badRequest("sessionId required");
  if (!body.userId || typeof body.userId !== "string") throw badRequest("userId required");
  if (!body.text || typeof body.text !== "string") throw badRequest("text required");
}

async function resolveConfig(api: Record<string, unknown>): Promise<OpenClawConfigLike> {
  for (const path of [["runtime", "config", "getConfig"], ["config", "get"], ["getConfig"]]) {
    const result = getNestedFn(api, path);
    if (result) return (await result.fn.call(result.owner)) as OpenClawConfigLike;
  }
  return {};
}

function assertAuthorized(req: IncomingMessage, token?: string): void {
  if (!token) return;
  const h = req.headers["x-dataclaw-token"] ?? req.headers["x-titan-openclaw-token"];  // backward compat
  const bearer = req.headers.authorization?.startsWith("Bearer ") ? req.headers.authorization.slice(7) : undefined;
  if (h !== token && bearer !== token) {
    const e = new Error("unauthorized"); Object.assign(e, { statusCode: 401 }); throw e;
  }
}

function readJson<T>(req: IncomingMessage): Promise<T> {
  return new Promise((resolve, reject) => {
    let data = ""; req.setEncoding("utf8");
    req.on("data", c => { data += c; });
    req.on("end", () => { try { resolve(JSON.parse(data || "{}") as T); } catch { reject(badRequest("invalid JSON")); } });
    req.on("error", reject);
  });
}

function writeJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status; res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(body));
}

function badRequest(msg: string): Error { const e = new Error(msg); Object.assign(e, { statusCode: 400 }); return e; }
function statusForError(err: unknown): number { return err && typeof err === "object" && "statusCode" in err ? Number((err as any).statusCode) : 500; }

function getNestedFn(root: unknown, path: string[]): { owner: unknown; fn: Function } | null {
  let cur = root, owner = root;
  for (const seg of path) {
    if (!cur || typeof cur !== "object" || !(seg in cur)) return null;
    owner = cur; cur = (cur as any)[seg];
  }
  return typeof cur === "function" ? { owner, fn: cur } : null;
}
