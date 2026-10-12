import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { Approvals } from "@/features/admin/approvals";

export const metadata: Metadata = { title: "Approvals" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.approvals.title" descriptionKey="pages.approvals.desc" />
      <Approvals />
    </>
  );
}
