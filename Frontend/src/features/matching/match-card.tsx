import Link from "next/link";
import { Check, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { formatKg, formatPerKg } from "@/utils/format";
import type { MatchDto, MatchFactor } from "@/types";

const LABEL: Record<MatchFactor, string> = { grade: "Grade match", quantity: "Quantity match", location: "Location match", price: "Price match", availability: "Availability match" };

export function MatchCard({ match, rank }: { match: MatchDto; rank: number }) {
  const l = match.listing;
  const hits = match.reasons.filter((r) => r.matched).length;
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground">Match #{rank}</p>
          <h2 className="font-display text-lg font-semibold">{l.crop} · Grade {l.grade} · {formatKg(l.quantityKg)}</h2>
          <p className="text-sm text-muted-foreground">{l.farmerName}, {l.location} · {formatPerKg(l.pricePerKg)}</p>
        </div>
        <div className="text-left sm:text-right">
          <p className="font-display text-2xl font-bold text-primary">{Math.round(match.score * 100)}%</p>
          <p className="text-xs text-muted-foreground">{hits} of {match.reasons.length} factors matched</p>
        </div>
      </div>
      <ul className="mt-4 grid gap-2 sm:grid-cols-2" aria-label="Why this matched">
        {match.reasons.map((r) => (
          <li key={r.factor} className="flex items-start gap-2 rounded-md bg-muted/60 px-3 py-2 text-sm">
            {r.matched ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-label="Matched" /> : <X className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-label="Not matched" />}
            <span><span className="font-medium">{LABEL[r.factor]}.</span> <span className="text-muted-foreground">{r.detail}</span></span>
          </li>
        ))}
      </ul>
      <Button asChild className="mt-4 w-full sm:w-auto"><Link href={`/buyer/marketplace/${match.listingId}`}>View listing</Link></Button>
    </Card>
  );
}
