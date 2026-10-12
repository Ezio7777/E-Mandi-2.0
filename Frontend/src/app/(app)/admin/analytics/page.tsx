import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { AdminAnalytics } from "@/features/admin/admin-analytics";

export const metadata: Metadata = { title: "Analytics" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.analytics.title" descriptionKey="pages.analytics.desc" />
      <AdminAnalytics />
    </>
  );
}
