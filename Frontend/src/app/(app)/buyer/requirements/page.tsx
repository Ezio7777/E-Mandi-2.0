import type { Metadata } from "next";
import { T } from "@/components/layout/t";
import { PageHeader } from "@/components/layout/page-header";
import { RequirementList } from "@/features/matching/requirement-list";
import { Button } from "@/components/ui/button";
import Link from "next/link";


export const metadata: Metadata = { title: "Requirements" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.requirements.title" descriptionKey="pages.requirements.desc" actions={<Button asChild><Link href="/buyer/requirements/new"><T k="pages.newRequirement.title" /></Link></Button>} />
      <RequirementList />
    </>
  );
}
