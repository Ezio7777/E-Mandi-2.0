"use client";
import { PanelLeftClose } from "lucide-react";
import { LogoMark } from "@/components/brand/logo-mark";
import { Button } from "@/components/ui/button";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { sidebarToggled } from "@/store/slices/ui.slice";
import { cn } from "@/utils/cn";
import { NavList } from "./nav-list";
import type { Role } from "@/types";

const EASE = "ease-[cubic-bezier(0.22,1,0.36,1)]";

/** md: icon rail. lg+: full sidebar the user can collapse. Width and labels animate; icons stay put. */
export function Sidebar({ role }: { role: Role }) {
  const dispatch = useAppDispatch();
  const userCollapsed = useAppSelector((s) => s.ui.sidebarCollapsed);
  const isLg = useMediaQuery("(min-width: 1024px)");
  const collapsed = !isLg || userCollapsed;

  return (
    <aside
      data-sidebar=""
      data-collapsed={collapsed}
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col gap-4 overflow-hidden border-r bg-surface p-3 md:flex",
        "transition-[width] duration-300 will-change-[width] motion-reduce:transition-none",
        EASE,
        collapsed ? "w-[4.5rem]" : "w-64",
      )}
    >
      <div className="flex h-12 shrink-0 items-center overflow-hidden pl-2">
        <LogoMark className="h-8 w-8 shrink-0" />
        <span
          aria-hidden={collapsed}
          className={cn(
            "overflow-hidden whitespace-nowrap font-display text-xl font-bold leading-none tracking-tight transition-[max-width,opacity,margin] duration-300 motion-reduce:transition-none",
            EASE,
            collapsed ? "ml-0 max-w-0 opacity-0" : "ml-2.5 max-w-[10rem] opacity-100",
          )}
        >
          E-Mandi<span className="ml-1 align-super text-[0.6rem] font-semibold text-primary">2.0</span>
        </span>
      </div>
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        <NavList role={role} collapsed={collapsed} />
      </div>
      <Button
        variant="ghost"
        size="icon"
        className="hidden self-end lg:inline-flex"
        onClick={() => dispatch(sidebarToggled())}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        aria-expanded={!collapsed}
      >
        <PanelLeftClose className={cn("transition-transform duration-300 motion-reduce:transition-none", EASE, collapsed && "rotate-180")} />
      </Button>
    </aside>
  );
}
