"use client";
import { CreditCard } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/skeletons";
import { ResponsiveTable } from "@/components/data/responsive-table";
import { usePayments } from "@/services/orders";
import { formatINR } from "@/utils/format";
import { PaymentStatusBadge } from "./payment-status";
import { useT } from "@/lib/i18n";

export function PaymentList() {
  const q = usePayments();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => d.length === 0} empty={<EmptyState icon={CreditCard} title={t("empty.paymentsTitle")} description={t("empty.paymentsBody")} />}>
      {(rows) => (
        <ResponsiveTable caption="Payments" rows={rows} rowKey={(p) => `${p.orderId}-${p.providerOrderId}`}
          columns={[
            { key: "order", header: t("labels.order"), primary: true, cell: (p) => p.orderId },
            { key: "amount", header: t("labels.amount"), cell: (p) => formatINR(p.amount) },
            { key: "provider", header: t("labels.provider"), cell: (p) => p.provider },
            { key: "status", header: t("labels.status"), cell: (p) => <PaymentStatusBadge status={p.status} /> },
          ]} />
      )}
    </QueryBoundary>
  );
}
