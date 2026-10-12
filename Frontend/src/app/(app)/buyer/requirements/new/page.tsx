import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { RequirementForm } from "@/features/matching/requirement-form";

export const metadata: Metadata = { title: "New requirement" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.newRequirement.title" descriptionKey="pages.newRequirement.desc" />
      <RequirementForm />
    </>
  );
}
