import { env } from "@/config/env";

export type RealtimeState = "idle" | "connecting" | "open" | "reconnecting" | "closed" | "error";
type Listener<T> = (msg: T) => void;

interface Options<T> {
  path: string;
  onMessage: Listener<T>;
  onState?: (s: RealtimeState) => void;
  parse?: (raw: string) => T;
  maxRetries?: number;
}

/** WebSocket with exponential backoff + jitter. Call the returned function to close and clean up. */
export function connectRealtime<T>({ path, onMessage, onState, parse, maxRetries = 6 }: Options<T>): () => void {
  // Demo mode has no socket server; screens fall back to polling.
  if (env.demoMode) return () => undefined;
  let ws: WebSocket | null = null;
  let attempt = 0;
  let everOpened = false;
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const decode = parse ?? ((raw: string) => JSON.parse(raw) as T);

  const open = () => {
    if (stopped) return;
    onState?.(attempt === 0 ? "connecting" : "reconnecting");
    ws = new WebSocket(`${env.wsUrl}${path}`);
    ws.onopen = () => { attempt = 0; everOpened = true; onState?.("open"); };
    ws.onmessage = (e: MessageEvent<string>) => { try { onMessage(decode(e.data)); } catch { /* ignore malformed frame */ } };
    ws.onerror = () => onState?.("error");
    ws.onclose = () => {
      if (stopped) return;
      // A socket that has never connected probably isn't offered by the backend: give up after 2 tries.
      if (attempt >= (everOpened ? maxRetries : Math.min(2, maxRetries))) { onState?.("closed"); return; }
      const delay = Math.min(1000 * 2 ** attempt, 15000) + Math.random() * 400;
      attempt += 1;
      onState?.("reconnecting");
      timer = setTimeout(open, delay);
    };
  };
  open();

  return () => { stopped = true; clearTimeout(timer); ws?.close(); onState?.("closed"); };
}
