"use client";
import { Logo } from "@/components/brand/logo";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { drawerToggled } from "@/store/slices/ui.slice";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { TourLauncher } from "@/features/tour/tour-launcher";
import { LanguageSwitcher } from "./language-switcher";
import { NavList } from "./nav-list";
import type { Role } from "@/types";

export function MobileDrawer({ role }: { role: Role }) {
  const dispatch = useAppDispatch();
  const open = useAppSelector((s) => s.ui.drawerOpen);
  return (
    <Sheet open={open} onOpenChange={(o) => dispatch(drawerToggled(o))}>
      <SheetContent side="left" className="pt-[max(1rem,env(safe-area-inset-top))]">
        <SheetTitle asChild><div><Logo /></div></SheetTitle>
        <SheetDescription className="sr-only">Site navigation</SheetDescription>
        <div className="mt-2 flex-1 overflow-y-auto">
          <NavList role={role} onNavigate={() => dispatch(drawerToggled(false))} />
        </div>
        <div className="flex items-center justify-between border-t pt-3 sm:hidden">
          <span className="text-sm text-muted-foreground">Language, theme, tour</span>
          <div className="flex">
            <LanguageSwitcher />
            <ThemeToggle />
            <TourLauncher onStart={() => dispatch(drawerToggled(false))} />
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
