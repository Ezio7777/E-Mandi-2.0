import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { OrderList } from "@/features/orders/order-list";

export const metadata: Metadata = { title: "Orders" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.farmerOrders.title" descriptionKey="pages.farmerOrders.desc" />
      <OrderList role="farmer" />
    </>
  );
}
