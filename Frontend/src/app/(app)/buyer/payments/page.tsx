import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { PaymentList } from "@/features/payments/payment-list";

export const metadata: Metadata = { title: "Payments" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.payments.title" descriptionKey="pages.payments.desc" />
      <PaymentList />
    </>
  );
}
