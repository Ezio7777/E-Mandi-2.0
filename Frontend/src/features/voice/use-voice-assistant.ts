"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { voiceApi } from "@/lib/api";
import type { Locale } from "@/types";

export type VoicePhase = "idle" | "listening" | "transcribing" | "searching" | "generating" | "error";
export interface Turn { id: string; question: string; answer: string; audioUrl?: string }

const BCP47: Record<Locale, string> = { en: "en-IN", hi: "hi-IN", kn: "kn-IN" };

export function useVoiceAssistant(language: Locale) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const stream = useRef<MediaStream | null>(null);

  const cleanup = () => { timers.current.forEach(clearTimeout); timers.current = []; stream.current?.getTracks().forEach((t) => t.stop()); stream.current = null; };
  useEffect(() => cleanup, []);

  const start = useCallback(async () => {
    setError(null);
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") { setPhase("error"); setError("Your browser can't record audio."); return; }
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setPhase("error"); setError("Microphone access was blocked. Allow it in your browser settings and try again."); return;
    }
    chunks.current = [];
    const rec = new MediaRecorder(stream.current);
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    rec.onstop = async () => {
      const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
      stream.current?.getTracks().forEach((t) => t.stop());
      setPhase("transcribing");
      // The backend does the work in one request; these labels mirror its pipeline for a conversational feel.
      timers.current.push(setTimeout(() => setPhase((p) => (p === "transcribing" ? "searching" : p)), 1200));
      timers.current.push(setTimeout(() => setPhase((p) => (p === "searching" ? "generating" : p)), 2600));
      try {
        const r = await voiceApi.ask(blob, language);
        setTurns((t) => [...t, { id: crypto.randomUUID(), question: r.transcript, answer: r.answer, audioUrl: r.audioUrl }]);
        setPhase("idle");
      } catch (e) {
        setPhase("error"); setError(e instanceof Error ? e.message : "Something went wrong.");
      } finally { timers.current.forEach(clearTimeout); timers.current = []; }
    };
    recorder.current = rec;
    rec.start();
    setPhase("listening");
  }, [language]);

  const stop = useCallback(() => { if (recorder.current?.state === "recording") recorder.current.stop(); }, []);

  /** Optional playback: prefers backend audio, otherwise the browser's speech synthesis. */
  const speak = useCallback((turn: Turn) => {
    if (turn.audioUrl) { void new Audio(turn.audioUrl).play(); return; }
    if ("speechSynthesis" in window) { const u = new SpeechSynthesisUtterance(turn.answer); u.lang = BCP47[language]; window.speechSynthesis.cancel(); window.speechSynthesis.speak(u); }
  }, [language]);

  return { phase, turns, error, start, stop, speak, busy: phase === "transcribing" || phase === "searching" || phase === "generating" };
}
