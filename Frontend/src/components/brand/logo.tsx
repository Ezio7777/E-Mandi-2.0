import { cn } from "@/utils/cn";
import { LogoMark } from "./logo-mark";

interface LogoProps {
  className?: string;
  markClassName?: string;
  /** hide the wordmark (mobile header, collapsed sidebar, favicon-like use) */
  compact?: boolean;
}

export function Logo({ className, markClassName, compact = false }: LogoProps) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark className={markClassName} />
      {!compact && (
        <span className="font-display text-xl font-bold leading-none tracking-tight text-foreground">
          E-Mandi
          <span className="ml-1 align-super text-[0.6rem] font-semibold text-primary">2.0</span>
        </span>
      )}
    </span>
  );
}
