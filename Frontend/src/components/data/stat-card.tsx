import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";

interface Props { label: string; value: string; hint?: string; icon?: LucideIcon }

export function StatCard({ label, value, hint, icon: Icon }: Props) {
  return (
    <Card className="min-w-0 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="min-w-0 text-sm text-muted-foreground">{label}</p>
        {Icon && <Icon className="h-4 w-4 text-primary" aria-hidden />}
      </div>
      <p className="mt-2 break-words font-display text-xl font-bold tabular-nums xs:text-2xl sm:text-3xl">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}
