"use client";
import { Minus, TrendingDown, TrendingUp } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/feedback/error-state";
import { formatPerKg } from "@/utils/format";
import { usePriceSuggestion } from "@/services/grading";
import type { Grade } from "@/types";

const trend = { up: { Icon: TrendingUp, label: "Prices rising", cls: "text-success" }, down: { Icon: TrendingDown, label: "Prices falling", cls: "text-danger" }, stable: { Icon: Minus, label: "Prices steady", cls: "text-muted-foreground" } } as const;

export function PriceCard({ crop, grade, location }: { crop: string; grade?: Grade; location: string }) {
  const q = usePriceSuggestion(crop, grade, location);
  if (q.isPending) return <Card className="space-y-3 p-5" data-tour="price-card"><Skeleton className="h-4 w-24" /><Skeleton className="h-10 w-32" /><Skeleton className="h-4 w-2/3" /></Card>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} title="Couldn't load a price suggestion" />;
  const p = q.data;
  const T = trend[p.trend];
  const span = Math.max(p.rangeMax - p.rangeMin, 1);
  const pos = Math.min(100, Math.max(0, ((p.suggested - p.rangeMin) / span) * 100));
  return (
    <Card className="p-5" data-tour="price-card">
      <p className="text-sm text-muted-foreground">Suggested price</p>
      <p className="font-display text-4xl font-bold">{formatPerKg(p.suggested)}</p>
      <div className="mt-4">
        <div className="relative h-2 rounded-full bg-muted" aria-hidden>
          <span className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-background bg-primary" style={{ left: `${pos}%` }} />
        </div>
        <div className="mt-1.5 flex justify-between text-xs text-muted-foreground"><span>{formatPerKg(p.rangeMin)}</span><span>Reference range</span><span>{formatPerKg(p.rangeMax)}</span></div>
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm">
        <span>Reference price <strong>{formatPerKg(p.referencePrice)}</strong></span>
        <span className={`inline-flex items-center gap-1 ${T.cls}`}><T.Icon className="h-4 w-4" aria-hidden />{T.label}</span>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">{p.explanation}</p>
      {p.source && <p className="mt-2 text-xs text-muted-foreground">Source: {p.source}</p>}
    </Card>
  );
}
