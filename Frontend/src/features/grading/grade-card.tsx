"use client";
import { AlertTriangle, CheckCircle2, Clock, Cpu } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useT } from "@/lib/i18n";
import { formatDate, formatNumber, formatPercent } from "@/utils/format";
import { cn } from "@/utils/cn";
import type { GradingJobDto } from "@/types";

const gradeColor = { A: "text-grade-a", B: "text-grade-b", C: "text-grade-c" } as const;
const STAGES = ["Uploading", "Analyzing", "AI grade ready"] as const;

export function GradingProgress({ job }: { job?: GradingJobDto }) {
  const stage = !job || job.status === "queued" ? 0 : job.status === "analyzing" ? 1 : 2;
  return (
    <Card className="p-5" data-tour="grading-card" aria-live="polite">
      <ol className="flex items-center gap-2">
        {STAGES.map((s, i) => (
          <li key={s} className="flex flex-1 items-center gap-2">
            <span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-medium", i < stage ? "bg-primary text-primary-foreground" : i === stage ? "bg-primary-soft text-primary ring-2 ring-primary" : "bg-muted text-muted-foreground")}>
              {i < stage ? "✓" : i + 1}
            </span>
            <span className={cn("hidden text-xs sm:inline", i === stage ? "font-medium" : "text-muted-foreground")}>{s}</span>
          </li>
        ))}
      </ol>
      <p className="mt-4 text-sm font-medium">{STAGES[stage]}…</p>
      <div className="mt-3 space-y-2"><Skeleton className="h-16 w-24" /><Skeleton className="h-4 w-2/3" /><Skeleton className="h-4 w-1/2" /></div>
    </Card>
  );
}

export function GradeCard({ result }: { result: NonNullable<GradingJobDto["result"]> }) {
  const { t } = useT();
  return (
    <Card className="p-5" data-tour="grade-result">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <p className="text-sm text-muted-foreground">{t("grading.grade")}</p>
          <p className={cn("font-display text-6xl font-bold leading-none", gradeColor[result.grade])} aria-label={`Grade ${result.grade}`}>{result.grade}</p>
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 pb-1 text-sm">
          <div><p className="text-muted-foreground">{t("grading.confidence")}</p><p className="text-lg font-semibold">{formatPercent(result.confidence)}</p></div>
          <div><p className="text-muted-foreground">{t("grading.defects")}</p><p className="text-lg font-semibold">{formatNumber(result.defectPercent)}%</p></div>
        </div>
      </div>

      {result.manualReviewRecommended && (
        <p role="status" className="mt-4 flex items-start gap-2 rounded-md bg-warning/15 px-3 py-2 text-sm text-warning">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> <span><strong>{t("grading.manualReview")}.</strong> AI confidence is low for this lot.</span>
        </p>
      )}

      <div className="mt-4">
        <p className="text-sm font-medium">Reason</p>
        <p className="mt-1 text-sm text-muted-foreground">{result.explanation}</p>
      </div>
      {result.issues.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Detected issues">
          {result.issues.map((i) => <li key={i} className="rounded-full border px-2.5 py-0.5 text-xs">{i}</li>)}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" aria-hidden />{formatDate(result.gradedAt, true)}</span>
        {result.provider && <span className="inline-flex items-center gap-1"><Cpu className="h-3 w-3" aria-hidden />{result.provider}</span>}
        <span className="inline-flex items-center gap-1"><CheckCircle2 className="h-3 w-3" aria-hidden />AI estimate, not a guarantee</span>
      </div>
    </Card>
  );
}
