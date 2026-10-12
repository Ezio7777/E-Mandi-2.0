"use client";
import { Info } from "lucide-react";
import { env } from "@/config/env";

/** Shown only when the app runs on its built-in sample data (no backend configured). */
export function DemoModeNote() {
  if (!env.demoMode) return null;
  return (
    <p className="flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <span>This site runs on built-in sample data, so no sign-up or backend is needed. Changes you make reset when you refresh.</span>
    </p>
  );
}
