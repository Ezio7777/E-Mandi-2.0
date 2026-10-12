"use client";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { LoadingScreen } from "@/components/brand/loading-screen";
import { ROLE_HOME } from "@/config/routes";
import { useSession } from "@/services/auth";
import type { Role } from "@/types";

/**
 * UX guard. The session query asks the backend who the user is; Redux state is only a cache.
 * Wrong role → redirect to own home. No session → login.
 */
export function RoleGuard({ role, children }: { role: Role; children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const session = useSession();
  const user = session.data;

  useEffect(() => {
    if (session.isError) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    else if (user && user.role !== role) router.replace(ROLE_HOME[user.role]);
  }, [session.isError, user, role, router, pathname]);

  if (session.isPending || !user || user.role !== role) return <LoadingScreen />;
  return <>{children}</>;
}
