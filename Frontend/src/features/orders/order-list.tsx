"use client";
import Link from "next/link";
import { ShoppingBasket } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/skeletons";
import { ResponsiveTable } from "@/components/data/responsive-table";
import { Badge } from "@/components/ui/badge";
import { PaymentStatusBadge } from "@/features/payments/payment-status";
import { useOrders } from "@/services/orders";
import { formatDate, formatINR, formatKg } from "@/utils/format";
import type { Role } from "@/types";
import { useT } from "@/lib/i18n";

export function OrderList({ role }: { role: Role }) {
  const q = useOrders();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => d.length === 0}
      empty={<EmptyState icon={ShoppingBasket} title={t("empty.ordersTitle")} description={role === "buyer" ? t("empty.ordersBuyer") : t("empty.ordersFarmer")} />}>
      {(orders) => (
        <ResponsiveTable tourId="orders-list" caption="Orders" rows={orders} rowKey={(o) => o.id}
          columns={[
            { key: "crop", header: t("labels.crop"), primary: true, cell: (o) => <Link href={`/${role}/orders/${o.id}`} className="font-medium text-primary hover:underline">{o.listing.crop} · {formatKg(o.quantityKg)}</Link> },
            { key: "party", header: role === "buyer" ? t("labels.farmer") : t("labels.buyer"), cell: (o) => (role === "buyer" ? o.farmerName : o.buyerName) },
            { key: "total", header: t("labels.total"), cell: (o) => formatINR(o.totalAmount) },
            { key: "status", header: t("labels.status"), cell: (o) => <Badge variant="default">{o.status.replace(/_/g, " ")}</Badge> },
            { key: "pay", header: t("labels.payment"), cell: (o) => <PaymentStatusBadge status={o.paymentStatus} /> },
            { key: "date", header: t("labels.date"), cell: (o) => formatDate(o.createdAt) },
          ]} />
      )}
    </QueryBoundary>
  );
}
