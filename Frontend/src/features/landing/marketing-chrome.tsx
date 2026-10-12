"use client";
import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { useT } from "@/lib/i18n";

export function MarketingHeader() {
  const { t } = useT();
  return (
    <header className="sticky top-0 z-40 border-b bg-background/85 pt-safe backdrop-blur">
      <div className="container flex h-14 items-center justify-between gap-2">
        <Link href="/" aria-label="E-Mandi home"><Logo /></Link>
        <nav aria-label="Site" className="flex items-center">
          <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex"><Link href="/how-it-works">{t("how.link")}</Link></Button>
          <LanguageSwitcher />
          <ThemeToggle />
          <Button asChild size="sm" className="ml-1"><Link href="/login">{t("auth.login")}</Link></Button>
        </nav>
      </div>
    </header>
  );
}

export function MarketingFooter() {
  const { t } = useT();
  return (
    <footer className="border-t bg-surface">
      <div className="container flex flex-col gap-4 py-8 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <Logo />
        <p>{t("how.footerNote")}</p>
        <div className="flex gap-4">
          <Link href="/how-it-works" className="hover:text-foreground">{t("how.link")}</Link>
          <Link href="/demo" className="hover:text-foreground">{t("landing.exploreDemo")}</Link>
          <Link href="/login" className="hover:text-foreground">{t("auth.login")}</Link>
        </div>
      </div>
    </footer>
  );
}
