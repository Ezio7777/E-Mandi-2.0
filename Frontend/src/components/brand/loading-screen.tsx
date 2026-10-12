import { LogoMark } from "./logo-mark";

export function LoadingScreen({ label = "Loading E-Mandi" }: { label?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-5 bg-background"
    >
      <div className="relative">
        <span className="absolute inset-0 animate-pulse-ring rounded-2xl bg-primary/30" aria-hidden />
        <LogoMark className="relative h-16 w-16" />
      </div>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}
