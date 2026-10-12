import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { OrderDetail } from "@/features/orders/order-detail";

export const metadata: Metadata = { title: "Checkout" };

export default async function Page({ params }: { params: Promise<{ orderId: string }> }) {
  const { orderId } = await params;
  return (
    <>
      <PageHeader titleKey="pages.checkout.title" descriptionKey="pages.checkout.desc" />
      <OrderDetail id={orderId} role="buyer" />
    </>
  );
}
