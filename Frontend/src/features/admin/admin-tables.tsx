"use client";
import { ScrollText } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/skeletons";
import { ResponsiveTable } from "@/components/data/responsive-table";
import { Badge } from "@/components/ui/badge";
import { PaymentStatusBadge } from "@/features/payments/payment-status";
import { useAdminAuditLogs, useAdminListings, useAdminTransactions, useAdminUsers, useGradingQueue } from "@/services/orders";
import { useT } from "@/lib/i18n";
import { formatDate, formatINR, formatKg, formatPerKg } from "@/utils/format";

function None() {
  const { t } = useT();
  return <EmptyState title={t("empty.nothingTitle")} description={t("empty.nothingBody")} />;
}
const none = <None />;

export function UsersTable() {
  const { t } = useT();
  const q = useAdminUsers();
  return <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => !d.length} empty={none}>{(rows) => (
    <ResponsiveTable caption="Users" rows={rows} rowKey={(u) => u.id} columns={[
      { key: "n", header: t("labels.name"), primary: true, cell: (u) => u.name },
      { key: "r", header: t("labels.role"), cell: (u) => <Badge variant="outline" className="capitalize">{u.role}</Badge> },
      { key: "c", header: t("labels.contact"), cell: (u) => u.email ?? u.phone ?? "—" },
      { key: "d", header: t("labels.type"), cell: (u) => (u.isDemo ? <Badge variant="warning">{t("labels.demo")}</Badge> : t("labels.real")) },
    ]} />)}</QueryBoundary>;
}

export function ListingsTable() {
  const { t } = useT();
  const q = useAdminListings();
  return <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => !d.length} empty={none}>{(rows) => (
    <ResponsiveTable caption="Listings" rows={rows} rowKey={(l) => l.id} columns={[
      { key: "c", header: t("labels.crop"), primary: true, cell: (l) => `${l.crop} · Grade ${l.grade}` },
      { key: "f", header: t("labels.farmer"), cell: (l) => l.farmerName },
      { key: "q", header: t("labels.quantity"), cell: (l) => formatKg(l.quantityKg) },
      { key: "p", header: t("labels.price"), cell: (l) => formatPerKg(l.pricePerKg) },
      { key: "s", header: t("labels.status"), cell: (l) => <Badge variant={l.status === "pending_review" ? "warning" : "muted"}>{l.status.replace("_", " ")}</Badge> },
    ]} />)}</QueryBoundary>;
}

export function TransactionsTable() {
  const { t } = useT();
  const q = useAdminTransactions();
  return <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => !d.length} empty={none}>{(rows) => (
    <ResponsiveTable caption="Transactions" rows={rows} rowKey={(o) => o.id} columns={[
      { key: "id", header: t("labels.transaction"), primary: true, cell: (o) => o.transactionId ?? o.id },
      { key: "c", header: t("labels.order"), cell: (o) => `${o.listing.crop} · ${formatKg(o.quantityKg)}` },
      { key: "a", header: t("labels.amount"), cell: (o) => formatINR(o.totalAmount) },
      { key: "p", header: t("labels.payment"), cell: (o) => <PaymentStatusBadge status={o.paymentStatus} /> },
      { key: "d", header: t("labels.date"), cell: (o) => formatDate(o.createdAt) },
    ]} />)}</QueryBoundary>;
}

export function DisputesTable() {
  const { t } = useT();
  const q = useAdminTransactions();
  return <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => !d.some((o) => o.status === "disputed" || o.paymentStatus === "disputed")} empty={<EmptyState title={t("empty.disputesTitle")} description={t("empty.disputesBody")} />}>{(rows) => (
    <ResponsiveTable caption="Disputes" rows={rows.filter((o) => o.status === "disputed" || o.paymentStatus === "disputed")} rowKey={(o) => o.id} columns={[
      { key: "id", header: t("labels.order"), primary: true, cell: (o) => o.id },
      { key: "c", header: t("labels.crop"), cell: (o) => o.listing.crop },
      { key: "a", header: t("labels.amount"), cell: (o) => formatINR(o.totalAmount) },
      { key: "p", header: t("labels.payment"), cell: (o) => <PaymentStatusBadge status={o.paymentStatus} /> },
    ]} />)}</QueryBoundary>;
}

export function GradingQueueTable() {
  const { t } = useT();
  const q = useGradingQueue();
  return <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => !d.length} empty={none}>{(rows) => (
    <ResponsiveTable caption="AI grading review" rows={rows} rowKey={(j) => j.jobId} columns={[
      { key: "j", header: t("labels.job"), primary: true, cell: (j) => j.jobId },
      { key: "g", header: t("labels.grade"), cell: (j) => (j.result ? `Grade ${j.result.grade}` : "—") },
      { key: "c", header: t("labels.confidence"), cell: (j) => (j.result ? `${Math.round(j.result.confidence * 100)}%` : "—") },
      { key: "r", header: t("labels.review"), cell: (j) => (j.result?.manualReviewRecommended ? <Badge variant="warning">{t("labels.manualReview")}</Badge> : <Badge variant="muted">{t("labels.okay")}</Badge>) },
    ]} />)}</QueryBoundary>;
}

export function AuditLogTable() {
  const { t } = useT();
  const q = useAdminAuditLogs();
  return <QueryBoundary query={q} skeleton={<ListSkeleton />} isEmpty={(d) => !d.length} empty={<EmptyState icon={ScrollText} title={t("empty.auditTitle")} description={t("empty.auditBody")} />}>{(rows) => (
    <ResponsiveTable tourId="audit-table" caption="Audit log" rows={rows} rowKey={(l) => l.id} columns={[
      { key: "a", header: t("labels.action"), primary: true, cell: (l) => l.action },
      { key: "w", header: t("labels.actor"), cell: (l) => l.actor },
      { key: "e", header: t("labels.entity"), cell: (l) => l.entity },
      { key: "t", header: t("labels.time"), cell: (l) => formatDate(l.at, true) },
    ]} />)}</QueryBoundary>;
}
