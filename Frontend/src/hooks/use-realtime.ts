"use client";
import { useEffect, useRef, useState } from "react";
import { connectRealtime, type RealtimeState } from "@/lib/realtime/realtime-client";

/** Subscribes on mount, cleans up on unmount. `enabled=false` skips connecting (e.g. polling fallback). */
export function useRealtime<T>(path: string | null, onMessage: (m: T) => void, enabled = true) {
  const [state, setState] = useState<RealtimeState>("idle");
  const handler = useRef(onMessage);
  useEffect(() => { handler.current = onMessage; });
  useEffect(() => {
    if (!path || !enabled) return;
    return connectRealtime<T>({ path, onMessage: (m) => handler.current(m), onState: setState });
  }, [path, enabled]);
  return state;
}
