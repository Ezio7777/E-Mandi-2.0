"use client";
import { useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { BadgeCheck, MapPin } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/feedback/error-state";
import { useListing } from "@/services/listings";
import { useCreateOrder } from "@/services/orders";
import { formatINR, formatKg, formatPerKg } from "@/utils/format";

export function ListingDetail({ id }: { id: string }) {
  const q = useListing(id);
  const router = useRouter();
  const order = useCreateOrder();
  const [qty, setQty] = useState<string>("");
  return (
    <QueryBoundary query={q} skeleton={<div className="grid gap-6 lg:grid-cols-2"><Skeleton className="aspect-[4/3]" /><Skeleton className="h-80" /></div>}>
      {(l) => {
        const n = Number(qty || l.quantityKg);
        const invalid = !(n > 0) || n > l.quantityKg;
        return (
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="grid gap-2">
              <div className="relative aspect-[4/3] overflow-hidden rounded-lg bg-muted">
                {l.images[0] && <Image src={l.images[0].url} alt={`${l.crop} lot`} fill sizes="(min-width:1024px) 50vw,100vw" className="object-cover" priority unoptimized={l.images[0].url.startsWith("/")} />}
              </div>
            </div>
            <Card className="space-y-4 p-5">
              <div className="flex items-start justify-between gap-3">
                <div><h2 className="font-display text-2xl font-bold">{l.crop}</h2><p className="flex items-center gap-1 text-sm text-muted-foreground"><MapPin className="h-3.5 w-3.5" aria-hidden />{l.location} · {l.farmerName}</p></div>
                <Badge variant="success" className="text-sm">Grade {l.grade}</Badge>
              </div>
              <p className="font-display text-3xl font-bold text-primary">{formatPerKg(l.pricePerKg)}</p>
              <ul className="flex flex-wrap gap-2 text-sm">
                <li><Badge variant="muted">{formatKg(l.quantityKg)} available</Badge></li>
                {l.farmerVerified && <li><Badge><BadgeCheck className="h-3 w-3" aria-hidden />Verified farmer</Badge></li>}
                <li><Badge variant="muted">AI graded</Badge></li>
              </ul>
              <div className="space-y-1.5">
                <Label htmlFor="qty">Quantity to buy (kg)</Label>
                <Input id="qty" type="number" inputMode="numeric" value={qty} placeholder={String(l.quantityKg)} onChange={(e) => setQty(e.target.value)} aria-invalid={invalid} />
                {invalid && <p role="alert" className="text-sm text-danger">Enter between 1 and {formatKg(l.quantityKg)}.</p>}
              </div>
              <div className="flex items-baseline justify-between border-t pt-4"><span className="text-muted-foreground">Total</span><span className="font-display text-2xl font-bold">{formatINR(n * l.pricePerKg)}</span></div>
              {order.isError && <ErrorState error={order.error} onRetry={() => order.reset()} title="Couldn't place the order" />}
              <Button size="lg" className="w-full" disabled={invalid} loading={order.isPending}
                onClick={() => order.mutate({ listingId: l.id, quantityKg: n }, { onSuccess: (o) => router.push(`/buyer/orders/${o.id}`) })}>
                Place order
              </Button>
            </Card>
          </div>
        );
      }}
    </QueryBoundary>
  );
}
