import { Check, Circle } from "lucide-react";
import { formatDate } from "@/utils/format";
import { cn } from "@/utils/cn";
import type { OrderDto, OrderStatus } from "@/types";

export const TIMELINE: { step: OrderStatus; label: string }[] = [
  { step: "created", label: "Order created" },
  { step: "reserved", label: "Inventory reserved" },
  { step: "payment_confirmed", label: "Payment confirmed" },
  { step: "farmer_confirmed", label: "Farmer confirmed" },
  { step: "fulfilled", label: "Fulfilled" },
  { step: "completed", label: "Completed" },
];

export function OrderTimeline({ order }: { order: OrderDto }) {
  const at = new Map(order.timeline.map((t) => [t.step, t.at]));
  const reached = TIMELINE.findLastIndex((s) => at.has(s.step));
  return (
    <ol className="relative space-y-5" data-tour="order-timeline" aria-label="Order progress">
      {TIMELINE.map((s, i) => {
        const done = i <= reached;
        const current = i === reached + 1;
        return (
          <li key={s.step} className="flex gap-3" aria-current={current ? "step" : undefined}>
            <div className="relative flex flex-col items-center">
              <span className={cn("z-10 flex h-7 w-7 items-center justify-center rounded-full border-2", done ? "border-primary bg-primary text-primary-foreground" : current ? "border-primary bg-background text-primary" : "border-border bg-background text-muted-foreground")}>
                {done ? <Check className="h-4 w-4" aria-hidden /> : <Circle className="h-3 w-3" aria-hidden />}
              </span>
              {i < TIMELINE.length - 1 && <span className={cn("absolute top-7 h-[calc(100%+0.25rem)] w-0.5", i < reached ? "bg-primary" : "bg-border")} aria-hidden />}
            </div>
            <div className="pb-1">
              <p className={cn("text-sm font-medium", !done && !current && "text-muted-foreground")}>{s.label}</p>
              <p className="text-xs text-muted-foreground">{done ? formatDate(at.get(s.step) ?? "", true) : current ? "Next" : "Pending"}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
