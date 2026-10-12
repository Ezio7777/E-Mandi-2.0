import type { Metadata } from "next";
import { T } from "@/components/layout/t";
import { PageHeader } from "@/components/layout/page-header";
import { FarmerDashboard } from "@/features/farmer/farmer-dashboard";
import { Button } from "@/components/ui/button";
import Link from "next/link";


export const metadata: Metadata = { title: "Dashboard" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.farmerDashboard.title" descriptionKey="pages.farmerDashboard.desc" actions={<Button asChild><Link href="/farmer/sell"><T k="nav.sellCrop" /></Link></Button>} />
      <FarmerDashboard />
    </>
  );
}
