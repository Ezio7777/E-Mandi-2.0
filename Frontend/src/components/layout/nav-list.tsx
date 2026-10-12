"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV } from "@/config/navigation";
import { useT } from "@/lib/i18n";
import { cn } from "@/utils/cn";
import type { Role } from "@/types";

interface Props { role: Role; collapsed?: boolean; onNavigate?: () => void }

/**
 * Icons never move: the link has a fixed left inset that centres the icon in the collapsed rail,
 * and only the label animates (max-width + opacity). That is what makes the sidebar feel smooth.
 */
export function NavList({ role, collapsed = false, onNavigate }: Props) {
  const pathname = usePathname();
  const { t } = useT();
  return (
    <nav aria-label="Main">
      <ul className="space-y-1">
        {NAV[role].map(({ href, labelKey, icon: Icon, tourId }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={href}>
              <Link
                href={href}
                onClick={onNavigate}
                data-tour={tourId}
                aria-current={active ? "page" : undefined}
                title={collapsed ? t(labelKey) : undefined}
                className={cn(
                  "flex min-h-touch items-center overflow-hidden rounded-md px-[0.875rem] text-sm font-medium transition-colors duration-200",
                  active ? "bg-primary-soft text-primary" : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )}
              >
                <Icon className="h-5 w-5 shrink-0" aria-hidden />
                <span
                  className={cn(
                    "overflow-hidden whitespace-nowrap transition-[max-width,opacity,margin] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none",
                    collapsed ? "ml-0 max-w-0 opacity-0" : "ml-3 max-w-[12rem] opacity-100",
                  )}
                >
                  {t(labelKey)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
