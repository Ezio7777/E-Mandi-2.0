import type { Metadata } from "next";
import { T } from "@/components/layout/t";
import { PageHeader } from "@/components/layout/page-header";
import { MyListings } from "@/features/farmer/my-listings";
import { Button } from "@/components/ui/button";
import Link from "next/link";


export const metadata: Metadata = { title: "My listings" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.farmerListings.title" descriptionKey="pages.farmerListings.desc" actions={<Button asChild><Link href="/farmer/sell"><T k="nav.sellCrop" /></Link></Button>} />
      <MyListings />
    </>
  );
}
