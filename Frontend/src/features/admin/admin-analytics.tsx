"use client";
import { Activity, Flag, Leaf, Receipt, ShoppingBasket, Sprout, Users, Wallet } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { ChartSkeleton, StatRowSkeleton } from "@/components/feedback/skeletons";
import { ChartCard } from "@/components/data/chart-card";
import { StatCard } from "@/components/data/stat-card";
import { useAdminAnalytics } from "@/services/orders";
import { compactNumber, formatINRCompact } from "@/utils/format";
import { useT } from "@/lib/i18n";

export function AdminAnalytics() {
  const q = useAdminAnalytics();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<div className="space-y-4"><StatRowSkeleton count={8} /><ChartSkeleton /></div>}>
      {(d) => (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-tour="admin-metrics">
            <StatCard label={t("dash.totalUsers")} value={compactNumber(d.totalUsers)} icon={Users} />
            <StatCard label={t("dash.activeFarmers")} value={compactNumber(d.activeFarmers)} icon={Sprout} />
            <StatCard label={t("dash.activeBuyers")} value={compactNumber(d.activeBuyers)} icon={ShoppingBasket} />
            <StatCard label={t("dash.listings")} value={compactNumber(d.listings)} icon={Leaf} />
            <StatCard label={t("dash.transactions")} value={compactNumber(d.transactions)} icon={Receipt} />
            <StatCard label={t("dash.transactionValue")} value={formatINRCompact(d.transactionValue)} icon={Wallet} />
            <StatCard label={t("dash.flagged")} value={String(d.flaggedActivities)} icon={Flag} hint={t("dash.flaggedHint")} />
            <StatCard label={t("dash.health")} value={t("dash.live")} icon={Activity} hint={t("dash.healthHint")} />
          </div>
          <ChartCard title={t("dash.txOverTime")} data={d.series} />
        </div>
      )}
    </QueryBoundary>
  );
}
