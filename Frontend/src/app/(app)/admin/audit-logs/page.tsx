import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { AuditLogTable } from "@/features/admin/admin-tables";

export const metadata: Metadata = { title: "Audit logs" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.auditLogs.title" descriptionKey="pages.auditLogs.desc" />
      <AuditLogTable />
    </>
  );
}
