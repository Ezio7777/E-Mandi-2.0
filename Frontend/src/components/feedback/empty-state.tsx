import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import { cn } from "@/utils/cn";

interface Props {
  title: string;
  description?: string;
  icon?: LucideIcon;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ title, description, icon: Icon = Inbox, action, className }: Props) {
  return (
    <div className={cn("flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-12 text-center", className)}>
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-soft text-primary">
        <Icon className="h-6 w-6" aria-hidden />
      </span>
      <h2 className="font-display text-lg font-semibold">{title}</h2>
      {description && <p className="max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}
