"use client";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/errors";
import { useT } from "@/lib/i18n";
import { cn } from "@/utils/cn";

interface Props {
  error?: unknown;
  title?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({ error, title, onRetry, className }: Props) {
  const { t } = useT();
  const message =
    error instanceof ApiError ? error.message : error instanceof Error ? error.message : "Please try again in a moment.";
  return (
    <div role="alert" className={cn("flex flex-col items-center gap-3 rounded-lg border border-danger/30 bg-danger/5 px-6 py-10 text-center", className)}>
      <AlertTriangle className="h-8 w-8 text-danger" aria-hidden />
      <h2 className="font-display text-lg font-semibold">{title ?? t("common.errorTitle")}</h2>
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          <RefreshCw /> {t("common.retry")}
        </Button>
      )}
    </div>
  );
}
