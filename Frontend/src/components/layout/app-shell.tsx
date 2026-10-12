"use client";
import { RoleGuard } from "@/features/auth/role-guard";
import { BottomNav } from "./bottom-nav";
import { Header } from "./header";
import { MobileDrawer } from "./mobile-drawer";
import { Sidebar } from "./sidebar";
import type { Role } from "@/types";

export function AppShell({ role, children }: { role: Role; children: React.ReactNode }) {
  return (
    <RoleGuard role={role}>
      <div data-shell-ready="" className="flex min-h-dvh">
        <Sidebar role={role} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header />
          <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-7xl flex-1 px-4 py-5 pb-24 sm:px-6 sm:py-8 md:pb-8">
            {children}
          </main>
        </div>
      </div>
      <MobileDrawer role={role} />
      <BottomNav role={role} />
    </RoleGuard>
  );
}
