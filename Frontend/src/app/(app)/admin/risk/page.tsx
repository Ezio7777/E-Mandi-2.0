import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { RiskList } from "@/features/admin/risk-list";

export const metadata: Metadata = { title: "Flagged activity" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.risk.title" descriptionKey="pages.risk.desc" />
      <RiskList />
    </>
  );
}
