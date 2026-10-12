"use client";
import Link from "next/link";
import { Leaf } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { CardGridSkeleton } from "@/components/feedback/skeletons";
import { Button } from "@/components/ui/button";
import { useMyListings } from "@/services/listings";
import { ListingCard } from "./listing-card";
import { useT } from "@/lib/i18n";

export function MyListings() {
  const q = useMyListings();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<CardGridSkeleton />} isEmpty={(d) => d.length === 0}
      empty={<EmptyState icon={Leaf} title={t("empty.listingsTitle")} description={t("empty.listingsBody")} action={<Button asChild><Link href="/farmer/sell">{t("nav.sellCrop")}</Link></Button>} />}>
      {(items) => (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-tour="listing-card">
          {items.map((l, i) => <ListingCard key={l.id} listing={l} href={`/farmer/listings/${l.id}`} showStatus priority={i < 2} />)}
        </div>
      )}
    </QueryBoundary>
  );
}
