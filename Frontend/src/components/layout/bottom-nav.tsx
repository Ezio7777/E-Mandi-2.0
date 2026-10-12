"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { NAV } from "@/config/navigation";
import { useT } from "@/lib/i18n";
import { cn } from "@/utils/cn";
import type { Role } from "@/types";

export function BottomNav({ role }: { role: Role }) {
  const pathname = usePathname();
  const { t } = useT();
  const items = NAV[role].filter((i) => i.primary).slice(0, 5);
  return (
    <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-30 border-t bg-background/95 pb-safe backdrop-blur md:hidden">
      <ul className="mx-auto grid max-w-md" style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}>
        {items.map(({ href, labelKey, icon: Icon, tourId }) => {
          const active = pathname === href || pathname.startsWith(`${href}/`);
          return (
            <li key={href}>
              <Link
                href={href}
                data-tour={tourId}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-[3.5rem] flex-col items-center justify-center gap-0.5 px-1 text-[0.68rem] font-medium",
                  active ? "text-primary" : "text-muted-foreground",
                )}
              >
                <Icon className="h-5 w-5" aria-hidden />
                <span className="w-full truncate text-center">{t(labelKey)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
