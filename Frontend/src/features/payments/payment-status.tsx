import { CheckCircle2, Clock, RotateCcw, ShieldAlert, XCircle, CircleDashed } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { PaymentStatus } from "@/types";

const map = {
  not_started: { label: "Not paid", Icon: CircleDashed, variant: "muted" },
  pending: { label: "Payment pending", Icon: Clock, variant: "warning" },
  success: { label: "Paid", Icon: CheckCircle2, variant: "success" },
  failed: { label: "Payment failed", Icon: XCircle, variant: "danger" },
  refunded: { label: "Refunded", Icon: RotateCcw, variant: "muted" },
  disputed: { label: "In dispute", Icon: ShieldAlert, variant: "danger" },
} as const;

export function PaymentStatusBadge({ status }: { status: PaymentStatus }) {
  const { label, Icon, variant } = map[status];
  return <Badge variant={variant}><Icon className="h-3 w-3" aria-hidden />{label}</Badge>;
}
