import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { DisputesTable } from "@/features/admin/admin-tables";

export const metadata: Metadata = { title: "Disputes" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.disputes.title" descriptionKey="pages.disputes.desc" />
      <DisputesTable />
    </>
  );
}
