"use client";
import { Target } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/skeletons";
import { useMatches } from "@/services/orders";
import { MatchCard } from "./match-card";
import { useT } from "@/lib/i18n";

export function MatchList({ requirementId, poll = false }: { requirementId?: string; poll?: boolean }) {
  const q = useMatches(requirementId, poll);
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<ListSkeleton rows={3} />} isEmpty={(d) => d.length === 0}
      empty={<EmptyState icon={Target} title={t("empty.matchesTitle")} description={t("empty.matchesBody")} />}>
      {(ms) => <div className="space-y-4">{[...ms].sort((a, b) => b.score - a.score).map((m, i) => <div key={m.listingId} data-tour={i === 0 ? "match-card" : undefined}><MatchCard match={m} rank={i + 1} /></div>)}</div>}
    </QueryBoundary>
  );
}
