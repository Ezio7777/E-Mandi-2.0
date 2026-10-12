import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { ProfileCard } from "@/features/farmer/profile-card";

export const metadata: Metadata = { title: "Profile" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.profile.title" descriptionKey="pages.profile.desc" />
      <ProfileCard />
    </>
  );
}
