"use client";
import { Boxes, Leaf, PackageCheck, Wallet } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { ChartSkeleton, StatRowSkeleton } from "@/components/feedback/skeletons";
import { ChartCard } from "@/components/data/chart-card";
import { StatCard } from "@/components/data/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useFarmerDashboard } from "@/services/listings";
import { formatINR, formatKg } from "@/utils/format";
import { useT } from "@/lib/i18n";

export function FarmerDashboard() {
  const q = useFarmerDashboard();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<div className="space-y-4"><StatRowSkeleton /><div className="grid gap-4 lg:grid-cols-2"><ChartSkeleton /><ChartSkeleton /></div></div>}>
      {(d) => {
        const total = d.gradingSummary.A + d.gradingSummary.B + d.gradingSummary.C || 1;
        return (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-tour="farmer-stats">
              <StatCard label={t("dash.activeListings")} value={String(d.activeListings)} icon={Leaf} />
              <StatCard label={t("dash.availableQty")} value={formatKg(d.availableQuantityKg)} icon={Boxes} />
              <StatCard label={t("dash.pendingOrders")} value={String(d.pendingOrders)} icon={PackageCheck} />
              <StatCard label={t("dash.earnings")} value={formatINR(d.earnings)} icon={Wallet} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <ChartCard title={t("dash.sales")} data={d.sales} kind="bar" />
              <ChartCard title={t("dash.cropPrices")} data={d.prices} />
            </div>
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-base">{t("dash.gradingSummary")}</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                {(["A", "B", "C"] as const).map((g) => (
                  <div key={g} className="flex items-center gap-3 text-sm">
                    <span className="w-14 font-medium">{t("labels.grade")} {g}</span>
                    <div className="h-2 flex-1 rounded-full bg-muted" role="img" aria-label={`${d.gradingSummary[g]} of ${total} lots`}>
                      <div className="h-full rounded-full" style={{ width: `${(d.gradingSummary[g] / total) * 100}%`, background: `hsl(var(--grade-${g.toLowerCase()}))` }} />
                    </div>
                    <span className="w-8 text-right tabular-nums text-muted-foreground">{d.gradingSummary[g]}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        );
      }}
    </QueryBoundary>
  );
}
