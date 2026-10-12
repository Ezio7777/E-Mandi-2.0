"use client";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { useT, type TranslationKey } from "@/lib/i18n";

const FLOWS: { role: TranslationKey; steps: TranslationKey[] }[] = [
  { role: "labels.farmer", steps: ["how.f1", "how.f2", "how.f3", "how.f4", "how.f5"] },
  { role: "labels.buyer", steps: ["how.b1", "how.b2", "how.b3", "how.b4", "how.b5"] },
  { role: "how.admin", steps: ["how.a1", "how.a2", "how.a3", "how.a4"] },
];

export function HowItWorks() {
  const { t } = useT();
  return (
    <div className="container max-w-4xl py-12 sm:py-16">
      <h1 className="text-4xl font-bold">{t("how.title")}</h1>
      <p className="mt-3 text-muted-foreground">{t("how.sub")}</p>
      <div className="mt-10 grid gap-6 md:grid-cols-3">
        {FLOWS.map((f) => (
          <section key={f.role} className="rounded-xl border bg-card p-5">
            <h2 className="text-xl font-semibold">{t(f.role)}</h2>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
              {f.steps.map((s) => <li key={s}>{t(s)}</li>)}
            </ol>
          </section>
        ))}
      </div>
      <Button asChild size="lg" className="mt-10"><Link href="/demo">{t("landing.exploreDemo")}</Link></Button>
    </div>
  );
}
