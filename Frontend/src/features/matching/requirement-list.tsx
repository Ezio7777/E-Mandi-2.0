"use client";
import Link from "next/link";
import { ClipboardList } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/skeletons";
import { ResponsiveTable } from "@/components/data/responsive-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRequirements } from "@/services/orders";
import { formatDate, formatINR, formatKg } from "@/utils/format";
import { useT } from "@/lib/i18n";

export function RequirementList() {
  const q = useRequirements();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => d.length === 0}
      empty={<EmptyState icon={ClipboardList} title={t("empty.reqTitle")} description={t("empty.reqBody")} action={<Button asChild><Link href="/buyer/requirements/new">{t("pages.newRequirement.title")}</Link></Button>} />}>
      {(rows) => (
        <ResponsiveTable caption="Requirements" rows={rows} rowKey={(r) => r.id}
          columns={[
            { key: "crop", header: t("labels.need"), primary: true, cell: (r) => `${formatKg(r.quantityKg)} Grade ${r.desiredGrade} ${r.crop}` },
            { key: "dest", header: t("labels.destination"), cell: (r) => r.destination },
            { key: "date", header: t("labels.by"), cell: (r) => formatDate(r.deliveryDate) },
            { key: "budget", header: t("labels.budget"), cell: (r) => formatINR(r.maxBudget) },
            { key: "status", header: t("labels.status"), cell: (r) => <Badge variant={r.status === "matched" ? "success" : "muted"}>{r.status}</Badge> },
          ]} />
      )}
    </QueryBoundary>
  );
}
