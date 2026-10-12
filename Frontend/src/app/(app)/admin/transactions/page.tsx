import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { TransactionsTable } from "@/features/admin/admin-tables";

export const metadata: Metadata = { title: "Transactions" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.transactions.title" descriptionKey="pages.transactions.desc" />
      <TransactionsTable />
    </>
  );
}
