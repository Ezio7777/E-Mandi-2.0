"use client";
import { useMemo, useState } from "react";
import { SearchX, SlidersHorizontal } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { CardGridSkeleton } from "@/components/feedback/skeletons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { ListingCard } from "@/features/farmer/listing-card";
import { useDebounce } from "@/hooks/use-debounce";
import { useMarketplace } from "@/services/listings";
import type { Grade, ListingFilters } from "@/types";

function Filters({ f, set, reset }: { f: ListingFilters; set: (p: Partial<ListingFilters>) => void; reset: () => void }) {
  const num = (v: string) => (v === "" ? undefined : Number(v));
  return (
    <div className="space-y-4">
      <div className="space-y-1.5"><Label htmlFor="crop">Crop</Label><Input id="crop" value={f.crop ?? ""} onChange={(e) => set({ crop: e.target.value || undefined })} placeholder="Tomato" /></div>
      <div className="space-y-1.5"><Label htmlFor="grade">Grade</Label>
        <Select id="grade" value={f.grade ?? ""} onChange={(e) => set({ grade: (e.target.value || undefined) as Grade | undefined })}>
          <option value="">Any grade</option><option value="A">Grade A</option><option value="B">Grade B</option><option value="C">Grade C</option>
        </Select></div>
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5"><Label htmlFor="minp">Min ₹/kg</Label><Input id="minp" type="number" inputMode="decimal" value={f.minPrice ?? ""} onChange={(e) => set({ minPrice: num(e.target.value) })} /></div>
        <div className="space-y-1.5"><Label htmlFor="maxp">Max ₹/kg</Label><Input id="maxp" type="number" inputMode="decimal" value={f.maxPrice ?? ""} onChange={(e) => set({ maxPrice: num(e.target.value) })} /></div>
      </div>
      <div className="space-y-1.5"><Label htmlFor="minq">Minimum quantity (kg)</Label><Input id="minq" type="number" inputMode="numeric" value={f.minQuantity ?? ""} onChange={(e) => set({ minQuantity: num(e.target.value) })} /></div>
      <div className="space-y-1.5"><Label htmlFor="loc">Location</Label><Input id="loc" value={f.location ?? ""} onChange={(e) => set({ location: e.target.value || undefined })} placeholder="Bangalore" /></div>
      <Button variant="ghost" className="w-full" onClick={reset}>Clear filters</Button>
    </div>
  );
}

export function Marketplace() {
  const [filters, setFilters] = useState<ListingFilters>({ sort: "newest", page: 1 });
  const [search, setSearch] = useState("");
  const debounced = useDebounce({ ...filters, q: search || undefined }, 350);
  const q = useMarketplace(debounced);
  const set = (p: Partial<ListingFilters>) => setFilters((f) => ({ ...f, ...p, page: 1 }));
  const reset = () => { setFilters({ sort: "newest", page: 1 }); setSearch(""); };
  const active = useMemo(() => Object.entries(filters).filter(([k, v]) => v !== undefined && k !== "sort" && k !== "page").length, [filters]);

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr]" data-tour="marketplace-filters">
      <aside className="hidden lg:block"><h2 className="mb-3 font-display text-lg font-semibold">Filters</h2><Filters f={filters} set={set} reset={reset} /></aside>
      <div className="min-w-0 space-y-4">
        <div className="flex flex-col gap-2 sm:flex-row">
          <Input aria-label="Search listings" type="search" placeholder="Search crops, farmers, places" value={search} onChange={(e) => setSearch(e.target.value)} className="flex-1" />
          <div className="flex gap-2">
            <Select aria-label="Sort" containerClassName="sm:w-48" value={filters.sort} onChange={(e) => set({ sort: e.target.value as ListingFilters["sort"] })}>
              <option value="newest">Newest</option><option value="price_asc">Price: low to high</option><option value="price_desc">Price: high to low</option><option value="quantity_desc">Most quantity</option>
            </Select>
            <Sheet>
              <SheetTrigger asChild><Button variant="outline" className="lg:hidden"><SlidersHorizontal />Filters{active > 0 && ` (${active})`}</Button></SheetTrigger>
              <SheetContent side="bottom" className="overflow-y-auto">
                <SheetTitle className="font-display text-lg font-semibold">Filters</SheetTitle><SheetDescription className="sr-only">Filter listings</SheetDescription>
                <Filters f={filters} set={set} reset={reset} />
              </SheetContent>
            </Sheet>
          </div>
        </div>
        <QueryBoundary query={q} skeleton={<CardGridSkeleton />} isEmpty={(d) => d.items.length === 0}
          empty={<EmptyState icon={SearchX} title="No listings match" description="Try removing a filter or searching a different crop." action={<Button variant="outline" onClick={reset}>Clear filters</Button>} />}>
          {(d) => (
            <>
              <p className="text-sm text-muted-foreground" aria-live="polite">{d.total} listing{d.total === 1 ? "" : "s"}</p>
              <div className={`grid gap-4 sm:grid-cols-2 xl:grid-cols-3 ${q.isPlaceholderData ? "opacity-60" : ""}`}>
                {d.items.map((l, i) => <ListingCard key={l.id} listing={l} href={`/buyer/marketplace/${l.id}`} priority={i < 3} />)}
              </div>
            </>
          )}
        </QueryBoundary>
      </div>
    </div>
  );
}
