import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { Marketplace } from "@/features/buyer/marketplace";

export const metadata: Metadata = { title: "Marketplace" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.marketplace.title" descriptionKey="pages.marketplace.desc" />
      <Marketplace />
    </>
  );
}
