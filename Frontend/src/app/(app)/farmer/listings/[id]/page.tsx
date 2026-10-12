import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { FarmerListingDetail } from "@/features/farmer/farmer-listing-detail";

export const metadata: Metadata = { title: "Listing" };

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <>
      <PageHeader titleKey="pages.listing.title" descriptionKey="pages.listing.desc" />
      <FarmerListingDetail id={id} />
    </>
  );
}
