import type { DataclawOutboundMessage } from "./types.js";

type Listener = (message: DataclawOutboundMessage) => void;

export class ResponseBroker {
  private listeners = new Map<string, Set<Listener>>();

  publish(message: DataclawOutboundMessage): void {
    const listeners = this.listeners.get(message.sessionId);
    if (!listeners) return;
    for (const listener of listeners) listener(message);
  }

  hasListeners(sessionId: string): boolean {
    const listeners = this.listeners.get(sessionId);
    return listeners !== undefined && listeners.size > 0;
  }

  subscribe(sessionId: string, listener: Listener): () => void {
    const listeners = this.listeners.get(sessionId) ?? new Set<Listener>();
    listeners.add(listener);
    this.listeners.set(sessionId, listeners);
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0) this.listeners.delete(sessionId);
    };
  }

  waitForFinal(
    sessionId: string,
    timeoutMs: number,
    quietMs = 2000,
  ): Promise<DataclawOutboundMessage | null> {
    return new Promise((resolve) => {
      let latest: DataclawOutboundMessage | null = null;
      let quietTimer: ReturnType<typeof setTimeout> | undefined;
      let unsubscribe: (() => void) | undefined;

      const finish = () => {
        clearTimeout(quietTimer);
        clearTimeout(deadline);
        unsubscribe?.();
        resolve(latest);
      };

      const deadline = setTimeout(finish, timeoutMs);
      unsubscribe = this.subscribe(sessionId, (message) => {
        latest = message;
        clearTimeout(quietTimer);
        quietTimer = setTimeout(finish, quietMs);
      });
    });
  }
}

export const responseBroker = new ResponseBroker();
