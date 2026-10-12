import { cn } from "@/utils/cn";

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden className={cn("skeleton-shimmer rounded-md bg-muted", className)} {...props} />;
}
