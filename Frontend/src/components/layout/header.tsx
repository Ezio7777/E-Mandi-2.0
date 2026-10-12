"use client";
import { LogOut, Menu } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { DemoBadge } from "@/features/demo/demo-badge";
import { TourLauncher } from "@/features/tour/tour-launcher";
import { NotificationBell } from "@/features/notifications/notification-bell";
import { useLogout } from "@/services/auth";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { drawerToggled } from "@/store/slices/ui.slice";
import { useT } from "@/lib/i18n";
import { LanguageSwitcher } from "./language-switcher";

export function Header() {
  const dispatch = useAppDispatch();
  const user = useAppSelector((s) => s.auth.user);
  const logout = useLogout();
  const { t } = useT();
  return (
    <header className="sticky top-0 z-30 flex items-center gap-2 border-b bg-background/90 px-3 pt-safe backdrop-blur sm:px-4">
      <div className="flex h-14 w-full items-center gap-1 sm:gap-2">
        <Button variant="ghost" size="icon" className="md:hidden" onClick={() => dispatch(drawerToggled(true))} aria-label="Open menu">
          <Menu />
        </Button>
        <Logo compact className="md:hidden" />
        <div className="ml-1 hidden min-w-0 md:block">
          <p className="truncate text-sm font-medium">{user?.name}</p>
          <p className="text-xs capitalize text-muted-foreground">{user?.role}</p>
        </div>
        <div className="ml-1"><DemoBadge /></div>
        <div className="ml-auto flex items-center">
          <div className="hidden sm:flex"><TourLauncher /></div>
          <NotificationBell />
          <div className="hidden sm:flex"><LanguageSwitcher /><ThemeToggle /></div>
          <Button variant="ghost" size="icon" onClick={() => logout.mutate()} aria-label={t("common.logout")}>
            <LogOut />
          </Button>
        </div>
      </div>
    </header>
  );
}
