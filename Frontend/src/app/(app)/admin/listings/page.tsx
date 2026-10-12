import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { ListingsTable } from "@/features/admin/admin-tables";

export const metadata: Metadata = { title: "Listings" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.adminListings.title" descriptionKey="pages.adminListings.desc" />
      <ListingsTable />
    </>
  );
}
