"use client";
import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertTriangle, MapPin, Trash2 } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useDeleteListing, useListing } from "@/services/listings";
import { useAppDispatch } from "@/store/hooks";
import { toastPushed } from "@/store/slices/notifications.slice";
import { formatDate, formatINR, formatKg, formatPerKg } from "@/utils/format";

const statusCopy = {
  active: { variant: "success", text: "Live. Buyers can see and order this listing." },
  pending_review: { variant: "warning", text: "Waiting for admin approval before it goes live." },
  draft: { variant: "muted", text: "Draft. Not visible to buyers." },
  sold_out: { variant: "muted", text: "Sold out. No stock left." },
  rejected: { variant: "danger", text: "Rejected by admin. Check the reason and relist if needed." },
} as const;

/** Farmer's own view of a listing: status, stock and value, with delete. No buying controls. */
export function FarmerListingDetail({ id }: { id: string }) {
  const q = useListing(id);
  const router = useRouter();
  const dispatch = useAppDispatch();
  const del = useDeleteListing();
  const [open, setOpen] = useState(false);

  return (
    <QueryBoundary query={q} skeleton={<div className="grid gap-6 lg:grid-cols-2"><Skeleton className="aspect-[4/3]" /><Skeleton className="h-80" /></div>}>
      {(l) => {
        const s = statusCopy[l.status];
        return (
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="relative aspect-[4/3] overflow-hidden rounded-lg bg-muted">
              {l.images[0] && <Image src={l.images[0].url} alt={`${l.crop} lot`} fill sizes="(min-width:1024px) 50vw,100vw" className="object-cover" priority unoptimized={l.images[0].url.startsWith("/")} />}
            </div>
            <Card className="space-y-4 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="font-display text-2xl font-bold">{l.crop}</h2>
                  <p className="flex items-center gap-1 text-sm text-muted-foreground"><MapPin className="h-3.5 w-3.5" aria-hidden />{l.location}</p>
                </div>
                <Badge variant="success" className="text-sm">Grade {l.grade}</Badge>
              </div>
              <p role="status" className="flex items-start gap-2 rounded-md bg-muted px-3 py-2 text-sm">
                <Badge variant={s.variant} className="shrink-0">{l.status.replace("_", " ")}</Badge><span>{s.text}</span>
              </p>
              <dl className="grid grid-cols-2 gap-4 text-sm">
                {[["Your price", formatPerKg(l.pricePerKg)], ["Stock left", formatKg(l.quantityKg)], ["Value of stock", formatINR(l.quantityKg * l.pricePerKg)], ["Listed on", formatDate(l.createdAt)]].map(([k, v]) => (
                  <div key={k}><dt className="text-muted-foreground">{k}</dt><dd className="font-semibold">{v}</dd></div>
                ))}
              </dl>
              <div className="flex flex-col gap-2 border-t pt-4 sm:flex-row">
                <Button asChild variant="outline"><Link href="/farmer/orders">View orders</Link></Button>
                <Button variant="destructive" onClick={() => setOpen(true)}><Trash2 /> Remove listing</Button>
              </div>
            </Card>

            <Dialog open={open} onOpenChange={setOpen}>
              <DialogContent>
                <DialogTitle className="flex items-center gap-2 font-display text-lg font-semibold"><AlertTriangle className="h-5 w-5 text-warning" aria-hidden />Remove this listing?</DialogTitle>
                <DialogDescription className="text-sm text-muted-foreground">Buyers will no longer see {l.crop}. Existing orders are not affected.</DialogDescription>
                {del.isError && <p role="alert" className="text-sm text-danger">{del.error.message}</p>}
                <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                  <DialogClose asChild><Button variant="outline">Keep it</Button></DialogClose>
                  <Button variant="destructive" loading={del.isPending}
                    onClick={() => del.mutate(l.id, { onSuccess: () => { dispatch(toastPushed("success", "Listing removed")); router.replace("/farmer/listings"); } })}>
                    Remove
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        );
      }}
    </QueryBoundary>
  );
}
