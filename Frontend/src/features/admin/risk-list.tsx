"use client";
import { ShieldCheck } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/skeletons";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useAdminRisk } from "@/services/orders";
import { formatDate } from "@/utils/format";
import { useT } from "@/lib/i18n";

const sev = { high: "danger", medium: "warning", low: "muted" } as const;

/** Copy is deliberately hedged: signals are "flagged for review", never accusations. */
export function RiskList() {
  const q = useAdminRisk();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => d.length === 0} empty={<EmptyState icon={ShieldCheck} title={t("empty.riskTitle")} description={t("empty.riskBody")} />}>
      {(rows) => (
        <ul className="space-y-3" data-tour="risk-list">
          {rows.map((r) => (
            <li key={r.id}>
              <Card className="p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2"><Badge variant={sev[r.severity]}>{r.severity} severity</Badge><Badge variant="outline">Flagged for review</Badge></div>
                  <time dateTime={r.at} className="text-xs text-muted-foreground">{formatDate(r.at, true)}</time>
                </div>
                <h2 className="mt-2 font-medium">{r.event}</h2>
                <p className="text-sm text-muted-foreground">Entity: {r.entity}</p>
                <p className="mt-2 text-sm"><span className="font-medium">Reason:</span> {r.reason}</p>
                <p className="mt-1 rounded-md bg-primary-soft px-3 py-2 text-sm text-primary"><span className="font-medium">Recommended action:</span> {r.recommendedAction}</p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </QueryBoundary>
  );
}
