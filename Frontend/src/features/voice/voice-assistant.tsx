"use client";
import { Loader2, Mic, Square, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/feedback/empty-state";
import { localeLabels, useT } from "@/lib/i18n";
import { useAppDispatch } from "@/store/hooks";
import { localeChanged } from "@/store/slices/theme.slice";
import { cn } from "@/utils/cn";
import type { Locale } from "@/types";
import { useVoiceAssistant, type VoicePhase } from "./use-voice-assistant";

const phaseKey = { listening: "voice.listening", transcribing: "voice.transcribing", searching: "voice.searching", generating: "voice.generating" } as const;

export function VoiceAssistant() {
  const { t, locale } = useT();
  const dispatch = useAppDispatch();
  const v = useVoiceAssistant(locale);
  const label = (p: VoicePhase) => (p in phaseKey ? t(phaseKey[p as keyof typeof phaseKey]) : t("voice.tapToSpeak"));

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <div role="group" aria-label="Language" className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
        {(Object.keys(localeLabels) as Locale[]).map((l) => (
          <button key={l} onClick={() => dispatch(localeChanged(l))} aria-pressed={l === locale}
            className={cn("min-h-touch rounded-md text-sm font-medium", l === locale ? "bg-background shadow-sm" : "text-muted-foreground")}>{localeLabels[l]}</button>
        ))}
      </div>

      <Card className="min-h-[16rem] space-y-4 p-4" aria-live="polite">
        {v.turns.length === 0 && <EmptyState icon={Mic} title="Ask about prices or selling" description="Try: “What is today's tomato price in Kolar?”" className="border-0" />}
        {v.turns.map((turn) => (
          <div key={turn.id} className="space-y-2">
            <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-2 text-sm text-primary-foreground">{turn.question}</p>
            <div className="flex max-w-[90%] items-start gap-2 rounded-2xl rounded-bl-sm bg-muted px-4 py-2 text-sm">
              <p className="flex-1">{turn.answer}</p>
              <Button size="icon" variant="ghost" className="-mr-2 -mt-1 h-9 w-9 min-h-0 min-w-0" onClick={() => v.speak(turn)} aria-label="Play answer"><Volume2 /></Button>
            </div>
          </div>
        ))}
        {v.busy && <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />{label(v.phase)}</p>}
        {v.error && <p role="alert" className="text-sm text-danger">{v.error}</p>}
      </Card>

      <div className="flex flex-col items-center gap-2 pb-2">
        <div className="relative">
          {v.phase === "listening" && <span className="absolute inset-0 animate-pulse-ring rounded-full bg-primary/40" aria-hidden />}
          <Button size="icon" className="relative h-20 w-20 rounded-full" disabled={v.busy} onClick={v.phase === "listening" ? v.stop : v.start} aria-label={v.phase === "listening" ? "Stop recording" : "Start recording"}>
            {v.phase === "listening" ? <Square className="!size-7" /> : <Mic className="!size-8" />}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">{label(v.phase)}</p>
      </div>
    </div>
  );
}
