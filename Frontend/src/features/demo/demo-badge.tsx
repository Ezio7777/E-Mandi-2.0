"use client";
import { FlaskConical } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useAppSelector } from "@/store/hooks";
import { useT } from "@/lib/i18n";

export function DemoBadge() {
  const active = useAppSelector((s) => s.demo.active);
  const { t } = useT();
  if (!active) return null;
  return (
    <Badge variant="warning" className="gap-1.5" data-tour="demo-badge">
      <FlaskConical className="h-3 w-3" aria-hidden /> {t("common.demoMode")}
    </Badge>
  );
}
