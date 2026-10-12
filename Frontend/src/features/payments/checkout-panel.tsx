"use client";
import { useState } from "react";
import { Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorState } from "@/components/feedback/error-state";
import { useConfirmPayment, useInitiatePayment, usePaymentStatus } from "@/services/orders";
import { formatINR } from "@/utils/format";
import { PaymentStatusBadge } from "./payment-status";
import { paymentProvider } from "./payment-provider";
import type { OrderDto } from "@/types";

export function CheckoutPanel({ order }: { order: OrderDto }) {
  const initiate = useInitiatePayment();
  const confirm = useConfirmPayment();
  const [flowError, setFlowError] = useState<Error | null>(null);
  const status = usePaymentStatus(order.id, order.paymentStatus === "pending");
  const current = status.data?.status ?? order.paymentStatus;

  const pay = async () => {
    setFlowError(null);
    try {
      const session = await initiate.mutateAsync(order.id);
      const payload = await paymentProvider.open(session);
      await confirm.mutateAsync({ orderId: order.id, payload });
    } catch (e) {
      setFlowError(e instanceof Error ? e : new Error("Payment failed"));
    }
  };
  const busy = initiate.isPending || confirm.isPending;

  return (
    <Card className="space-y-4 p-5" data-tour="checkout-panel">
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Payment</h2>
        <PaymentStatusBadge status={current} />
      </div>
      <div className="flex items-baseline justify-between"><span className="text-sm text-muted-foreground">Amount due</span><span className="font-display text-2xl font-bold">{formatINR(order.totalAmount)}</span></div>
      {flowError && <ErrorState error={flowError} title="Payment didn't go through" onRetry={pay} />}
      {current === "pending" && <p role="status" className="text-sm text-muted-foreground">Waiting for confirmation from your bank. This page updates automatically.</p>}
      {current === "success" && <p role="status" className="text-sm text-success">Payment received. Your money is held until the order is fulfilled.</p>}
      {(current === "not_started" || current === "failed") && (
        <Button size="lg" className="w-full" loading={busy} onClick={pay}><Lock /> Pay {formatINR(order.totalAmount)}</Button>
      )}
      <p className="text-xs text-muted-foreground">Test mode. No real money is charged.</p>
    </Card>
  );
}
