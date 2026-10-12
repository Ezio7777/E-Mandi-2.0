import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { GradingQueueTable } from "@/features/admin/admin-tables";

export const metadata: Metadata = { title: "AI grading" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.grading.title" descriptionKey="pages.grading.desc" />
      <GradingQueueTable />
    </>
  );
}
