import { Skeleton } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";

export const CardGridSkeleton = ({ count = 6 }: { count?: number }) => (
  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy aria-label="Loading">
    {Array.from({ length: count }).map((_, i) => (
      <Card key={i} className="overflow-hidden">
        <Skeleton className="aspect-[4/3] w-full rounded-none" />
        <div className="space-y-2 p-4">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-4 w-1/3" />
        </div>
      </Card>
    ))}
  </div>
);

export const StatRowSkeleton = ({ count = 4 }: { count?: number }) => (
  <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-busy aria-label="Loading">
    {Array.from({ length: count }).map((_, i) => (
      <Card key={i} className="space-y-3 p-4">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-8 w-24" />
      </Card>
    ))}
  </div>
);

export const ListSkeleton = ({ rows = 5 }: { rows?: number }) => (
  <div className="space-y-3" aria-busy aria-label="Loading">
    {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}
  </div>
);

export const ChartSkeleton = () => <Skeleton className="h-64 w-full" aria-label="Loading chart" />;
