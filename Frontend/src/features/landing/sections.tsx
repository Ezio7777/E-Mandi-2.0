"use client";
import Link from "next/link";
import { Bot, Camera, FileSearch, HandCoins, Handshake, LockKeyhole, Mic, Route, Search, ShieldCheck, Target, Wheat } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DemoButtons } from "@/features/demo/demo-buttons";
import { useT, type TranslationKey } from "@/lib/i18n";

type Icon = React.ElementType;
type Item = { icon: Icon; t: TranslationKey; b: TranslationKey };

const Section = ({ id, title, intro, children, tone }: { id?: string; title: string; intro?: string; children: React.ReactNode; tone?: "surface" }) => (
  <section id={id} className={`scroll-mt-16 border-b py-14 sm:py-20 ${tone === "surface" ? "bg-surface" : ""}`}>
    <div className="container">
      <h2 className="max-w-2xl text-3xl font-bold sm:text-4xl">{title}</h2>
      {intro && <p className="mt-3 max-w-2xl text-muted-foreground">{intro}</p>}
      <div className="mt-8">{children}</div>
    </div>
  </section>
);

function Steps({ items }: { items: Item[] }) {
  const { t } = useT();
  return (
    <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {items.map(({ icon: Icon, t: title, b }, i) => (
        <li key={title} className="rounded-xl border bg-card p-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-soft text-primary"><Icon className="h-5 w-5" aria-hidden /></span>
            <span className="text-sm text-muted-foreground">{t("home.step")} {i + 1}</span>
          </div>
          <h3 className="mt-3 text-lg font-semibold">{t(title)}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{t(b)}</p>
        </li>
      ))}
    </ol>
  );
}

function Features({ items, cols }: { items: Item[]; cols: string }) {
  const { t } = useT();
  return (
    <div className={`grid gap-4 ${cols}`}>
      {items.map(({ icon: Icon, t: title, b }) => (
        <div key={title} className="rounded-xl border bg-card p-5">
          <Icon className="h-6 w-6 text-primary" aria-hidden />
          <h3 className="mt-3 text-lg font-semibold">{t(title)}</h3>
          <p className="mt-1 text-sm text-muted-foreground">{t(b)}</p>
        </div>
      ))}
    </div>
  );
}

export function LandingSections() {
  const { t } = useT();
  return (
    <>
      <Section id="how" title={t("home.h1t")} intro={t("home.h1i")}>
        <Features cols="md:grid-cols-3" items={[
          { icon: Bot, t: "home.f1t", b: "home.f1b" }, { icon: HandCoins, t: "home.f2t", b: "home.f2b" }, { icon: Handshake, t: "home.f3t", b: "home.f3b" },
        ]} />
      </Section>

      <Section title={t("home.farmerTitle")} tone="surface">
        <Steps items={[
          { icon: Camera, t: "home.fs1t", b: "home.fs1b" }, { icon: Wheat, t: "home.fs2t", b: "home.fs2b" },
          { icon: Bot, t: "home.fs3t", b: "home.fs3b" }, { icon: HandCoins, t: "home.fs4t", b: "home.fs4b" },
        ]} />
      </Section>

      <Section title={t("home.buyerTitle")}>
        <Steps items={[
          { icon: Search, t: "home.bs1t", b: "home.bs1b" }, { icon: Target, t: "home.bs2t", b: "home.bs2b" },
          { icon: FileSearch, t: "home.bs3t", b: "home.bs3b" }, { icon: LockKeyhole, t: "home.bs4t", b: "home.bs4b" },
        ]} />
      </Section>

      <Section title={t("home.aiTitle")} intro={t("home.aiIntro")} tone="surface">
        <Features cols="md:grid-cols-2" items={[
          { icon: Bot, t: "home.a1t", b: "home.a1b" }, { icon: Target, t: "home.a2t", b: "home.a2b" },
          { icon: Mic, t: "home.a3t", b: "home.a3b" }, { icon: Route, t: "home.a4t", b: "home.a4b" },
        ]} />
      </Section>

      <Section title={t("home.secTitle")}>
        <Features cols="md:grid-cols-3" items={[
          { icon: LockKeyhole, t: "home.c1t", b: "home.c1b" }, { icon: ShieldCheck, t: "home.c2t", b: "home.c2b" }, { icon: FileSearch, t: "home.c3t", b: "home.c3b" },
        ]} />
      </Section>

      <section className="bg-primary-soft/50 py-14 sm:py-20">
        <div className="container max-w-3xl text-center">
          <h2 className="text-3xl font-bold sm:text-4xl">{t("home.ctaTitle")}</h2>
          <p className="mx-auto mt-3 max-w-xl text-muted-foreground">{t("home.ctaSub")}</p>
          <div className="mx-auto mt-8 max-w-2xl text-left"><DemoButtons /></div>
          <Button asChild variant="link" className="mt-4"><Link href="/how-it-works">{t("home.ctaLink")}</Link></Button>
        </div>
      </section>
    </>
  );
}
