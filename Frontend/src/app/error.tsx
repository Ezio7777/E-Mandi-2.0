"use client";
import { ErrorState } from "@/components/feedback/error-state";

export default function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return <main id="main-content" className="mx-auto flex min-h-dvh max-w-lg items-center px-4"><ErrorState error={error} onRetry={reset} className="w-full" /></main>;
}
