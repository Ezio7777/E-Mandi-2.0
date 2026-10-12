import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { OrderDetail } from "@/features/orders/order-detail";

export const metadata: Metadata = { title: "Order" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <PageHeader titleKey="pages.order.title" descriptionKey="pages.order.desc" />
      <OrderDetail id={id} role="farmer" />
    </>
  );
}
