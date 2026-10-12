import Image from "next/image";
import Link from "next/link";
import { BadgeCheck, MapPin } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { formatKg, formatPerKg } from "@/utils/format";
import { cn } from "@/utils/cn";
import type { ListingDto } from "@/types";

// Solid themed chip so the text stays readable over any photo, in light and dark.
const gradeCls = { A: "bg-background text-grade-a ring-1 ring-grade-a/40", B: "bg-background text-grade-b ring-1 ring-grade-b/40", C: "bg-background text-grade-c ring-1 ring-grade-c/40" } as const;
const statusVariant = { active: "success", pending_review: "warning", draft: "muted", sold_out: "muted", rejected: "danger" } as const;

export function ListingCard({ listing, href, showStatus, priority }: { listing: ListingDto; href: string; showStatus?: boolean; priority?: boolean }) {
  const img = listing.images[0]?.url;
  return (
    <Card className="group overflow-hidden transition-[box-shadow,transform] duration-300 ease-out hover:-translate-y-0.5 hover:shadow-md motion-reduce:transition-none motion-reduce:hover:translate-y-0">
      <Link href={href} className="block focus-visible:outline-none">
        <div className="relative aspect-[4/3] bg-muted">
          {img ? <Image src={img} alt={`${listing.crop} lot`} fill sizes="(min-width:1280px) 30vw,(min-width:640px) 45vw,100vw" className="object-cover" priority={priority} unoptimized={img.endsWith(".svg") || img.startsWith("/")} /> : null}
          <span className={cn("absolute left-3 top-3 rounded-full px-2.5 py-0.5 text-xs font-bold shadow-sm", gradeCls[listing.grade])}>Grade {listing.grade}</span>
        </div>
        <div className="space-y-2 p-4">
          <div className="flex items-start justify-between gap-2">
            <h2 className="font-display text-lg font-semibold leading-tight">{listing.crop}</h2>
            <p className="shrink-0 font-display text-lg font-bold text-primary">{formatPerKg(listing.pricePerKg)}</p>
          </div>
          <p className="text-sm text-muted-foreground">{formatKg(listing.quantityKg)} available</p>
          <p className="flex items-center gap-1 text-sm text-muted-foreground"><MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden /><span className="truncate">{listing.location} · {listing.farmerName}</span></p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {listing.farmerVerified && <Badge variant="default"><BadgeCheck className="h-3 w-3" aria-hidden />Verified farmer</Badge>}
            {listing.availableFrom && <Badge variant="muted">Available {new Date(listing.availableFrom).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}</Badge>}
            {showStatus && <Badge variant={statusVariant[listing.status]}>{listing.status.replace("_", " ")}</Badge>}
          </div>
        </div>
      </Link>
    </Card>
  );
}
