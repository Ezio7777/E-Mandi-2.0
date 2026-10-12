"use client";
import { useState } from "react";
import { ClipboardCheck } from "lucide-react";
import { QueryBoundary } from "@/components/feedback/query-boundary";
import { EmptyState } from "@/components/feedback/empty-state";
import { ListSkeleton } from "@/components/feedback/skeletons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useT } from "@/lib/i18n";
import { useAdminApprovals, useDecideApproval } from "@/services/orders";
import { useAppDispatch } from "@/store/hooks";
import { toastPushed } from "@/store/slices/notifications.slice";
import { formatDate } from "@/utils/format";
import type { ApprovalDto } from "@/types";

function ApprovalCard({ a }: { a: ApprovalDto }) {
  const { t } = useT();
  const dispatch = useAppDispatch();
  const decide = useDecideApproval();
  const [note, setNote] = useState("");
  const pending = a.status === "pending";
  const act = (action: "approve" | "reject" | "request_review") =>
    decide.mutate({ id: a.id, action, note: note || undefined }, {
      onSuccess: () => dispatch(toastPushed("success", "Decision recorded in the audit log")),
      onError: (e) => dispatch(toastPushed("error", e.message)),
    });
  return (
    <Card className="space-y-3 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">{a.title}</h2>
        <Badge variant={pending ? "warning" : a.status === "approved" ? "success" : "muted"}>{pending ? t("admin.approvalRequired") : a.status.replace("_", " ")}</Badge>
      </div>
      <p className="text-sm text-muted-foreground"><span className="font-medium text-foreground">Reason:</span> {a.reason}</p>
      {pending && (
        <>
          <div className="space-y-1.5"><Label htmlFor={`note-${a.id}`}>Note (optional)</Label><Input id={`note-${a.id}`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add context for the audit trail" /></div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button onClick={() => act("approve")} disabled={decide.isPending}>{t("admin.approve")}</Button>
            <Button variant="destructive" onClick={() => act("reject")} disabled={decide.isPending}>{t("admin.reject")}</Button>
            <Button variant="outline" onClick={() => act("request_review")} disabled={decide.isPending}>{t("admin.requestReview")}</Button>
          </div>
        </>
      )}
      {a.history.length > 0 && (
        <details className="text-sm"><summary className="min-h-touch cursor-pointer py-2 font-medium">Audit history ({a.history.length})</summary>
          <ol className="space-y-1 border-l pl-3">{a.history.map((h, i) => <li key={i} className="text-muted-foreground"><span className="text-foreground">{h.actor}</span> {h.action}{h.note ? `: ${h.note}` : ""} · {formatDate(h.at, true)}</li>)}</ol>
        </details>
      )}
    </Card>
  );
}

export function Approvals() {
  const q = useAdminApprovals();
  const { t } = useT();
  return (
    <QueryBoundary query={q} skeleton={<ListSkeleton rows={3} />} isEmpty={(d) => d.length === 0} empty={<EmptyState icon={ClipboardCheck} title={t("empty.approvalsTitle")} description={t("empty.approvalsBody")} />}>
      {(rows) => <div className="space-y-4">{rows.map((a) => <ApprovalCard key={a.id} a={a} />)}</div>}
    </QueryBoundary>
  );
}
