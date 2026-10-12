import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { SellWizard } from "@/features/farmer/sell-wizard";

export const metadata: Metadata = { title: "Sell a crop" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.sell.title" descriptionKey="pages.sell.desc" />
      <SellWizard />
    </>
  );
}
