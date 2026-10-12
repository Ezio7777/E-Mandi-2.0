"use client";
import Link from "next/link";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CheckoutPanel } from "@/features/payments/checkout-panel";
import { PaymentStatusBadge } from "@/features/payments/payment-status";
import { useConfirmOrder, useOrder } from "@/services/orders";
import { formatDate, formatINR, formatKg, formatPerKg } from "@/utils/format";
import { OrderTimeline } from "./order-timeline";
import type { Role } from "@/types";

export function OrderDetail({ id, role }: { id: string; role: Role }) {
  const q = useOrder(id);
  const confirm = useConfirmOrder();
  return (
    <QueryBoundary query={q} skeleton={<div className="grid gap-4 lg:grid-cols-3"><Skeleton className="h-80 lg:col-span-2" /><Skeleton className="h-80" /></div>}>
      {(o) => (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <Card className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h2 className="font-display text-xl font-semibold">{o.listing.crop} · Grade {o.listing.grade}</h2>
                  <p className="text-sm text-muted-foreground">Order {o.id}</p>
                </div>
                <div className="flex gap-2"><Badge variant="default">{o.status.replace(/_/g, " ")}</Badge><PaymentStatusBadge status={o.paymentStatus} /></div>
              </div>
              <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
                {[["Farmer", o.farmerName], ["Buyer", o.buyerName], ["Quantity", formatKg(o.quantityKg)], ["Price", formatPerKg(o.pricePerKg)], ["Total", formatINR(o.totalAmount)], ["Created", formatDate(o.createdAt, true)], ["Transaction ID", o.transactionId ?? "Not yet issued"]].map(([k, v]) => (
                  <div key={k} className="min-w-0"><dt className="text-muted-foreground">{k}</dt><dd className="break-words font-medium">{v}</dd></div>
                ))}
              </dl>
            </Card>
            <Card className="p-5"><h2 className="mb-4 font-display text-lg font-semibold">Transaction timeline</h2><OrderTimeline order={o} /></Card>
          </div>
          <div className="space-y-4">
            {role === "buyer" && <CheckoutPanel order={o} />}
            {role === "farmer" && o.status === "payment_confirmed" && (
              <Card className="space-y-3 p-5">
                <h2 className="font-display text-lg font-semibold">Confirm this order</h2>
                <p className="text-sm text-muted-foreground">Payment is confirmed. Confirm that you can deliver.</p>
                <Button className="w-full" loading={confirm.isPending} onClick={() => confirm.mutate(o.id)}>Confirm order</Button>
              </Card>
            )}
            <Button asChild variant="outline" className="w-full"><Link href={`/${role}/orders`}>Back to orders</Link></Button>
          </div>
        </div>
      )}
    </QueryBoundary>
  );
}
