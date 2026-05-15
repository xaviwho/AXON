// Auto-reconnecting WebSocket for the multiplexed /live stream.
//
// Exposes a single `subscribeLive` hook-friendly API. Each subscriber
// gets every event; we don't filter at the socket layer because the
// dashboard wants all of them and the bandwidth is negligible.
// The URL is same-origin (`ws://<host>/live`) — Vite proxies it to
// console_api on the host; see vite.config.ts.

export type LiveEvent =
  | { event: "hello"; payload: { snapshot: LiveEvent[] } }
  | { event: "anomaly"; payload: AnyDict }
  | { event: "scene"; payload: AnyDict }
  | { event: "plan"; payload: AnyDict }
  | { event: "audit"; payload: AnyDict }
  | { event: "alert"; payload: AnyDict }
  | { event: "slice"; payload: AnyDict };

type AnyDict = Record<string, unknown>;

export type LiveListener = (e: LiveEvent) => void;

class LiveBus {
  private ws: WebSocket | null = null;
  private listeners = new Set<LiveListener>();
  private reconnectDelay = 1000;
  private stopped = false;

  start(): void {
    if (this.ws || this.stopped) return;
    // Same-origin /live — Vite proxies it to console_api's WebSocket on the host.
    const wsProto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${window.location.host}/live`);
    this.ws = ws;

    ws.addEventListener("open", () => {
      this.reconnectDelay = 1000;
    });
    ws.addEventListener("message", (ev) => {
      try {
        const msg = JSON.parse(ev.data as string) as LiveEvent;
        for (const l of this.listeners) l(msg);
      } catch {
        /* drop malformed frame */
      }
    });
    ws.addEventListener("close", () => {
      this.ws = null;
      if (this.stopped) return;
      const delay = this.reconnectDelay;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15_000);
      setTimeout(() => this.start(), delay);
    });
    ws.addEventListener("error", () => {
      // close handler will reconnect
      try { ws.close(); } catch { /* ignore */ }
    });
  }

  subscribe(l: LiveListener): () => void {
    this.listeners.add(l);
    this.start();
    return () => {
      this.listeners.delete(l);
    };
  }
}

export const liveBus = new LiveBus();

export function subscribeLive(l: LiveListener): () => void {
  return liveBus.subscribe(l);
}
