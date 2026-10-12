import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/page-header";
import { UsersTable } from "@/features/admin/admin-tables";

export const metadata: Metadata = { title: "Users" };

export default function Page() {
  return (
    <>
      <PageHeader titleKey="pages.users.title" descriptionKey="pages.users.desc" />
      <UsersTable />
    </>
  );
}
