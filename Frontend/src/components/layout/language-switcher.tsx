"use client";
import { Languages } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { localeLabels } from "@/lib/i18n";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { localeChanged } from "@/store/slices/theme.slice";
import type { Locale } from "@/types";

export function LanguageSwitcher() {
  const dispatch = useAppDispatch();
  const locale = useAppSelector((s) => s.theme.locale);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change language"><Languages /></Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {(Object.keys(localeLabels) as Locale[]).map((l) => (
          <DropdownMenuItem key={l} onSelect={() => dispatch(localeChanged(l))}>
            {localeLabels[l]} {l === locale && <span className="ml-auto text-primary">●</span>}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
