import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { MatchList } from "@/features/matching/match-list";

export const metadata: Metadata = { title: "Matches" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.matches.title" descriptionKey="pages.matches.desc" />
      <MatchList />
    </>
  );
}
