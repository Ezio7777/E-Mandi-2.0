"use client";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight, BadgeCheck, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

/** The hero's memorable element is a live-looking AI grade card, since grading is the product's core promise. */
function GradePreview() {
  return (
    <div className="w-full max-w-sm rounded-2xl border bg-card p-5 shadow-xl">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Tomato · 800 kg · Hosur</p>
        <span className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-xs font-medium text-success"><BadgeCheck className="h-3 w-3" />Verified grade</span>
      </div>
      <div className="mt-4 flex items-end gap-4">
        <span className="font-display text-7xl font-bold leading-none text-grade-a">A</span>
        <div className="pb-1 text-sm">
          <p className="font-semibold">94% confidence</p>
          <p className="text-muted-foreground">2.5% surface defects</p>
        </div>
      </div>
      <p className="mt-4 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">Minor surface bruising on a few fruits. Colour and firmness are consistent.</p>
      <div className="mt-4 border-t pt-4">
        <p className="text-xs text-muted-foreground">Suggested price</p>
        <p className="font-display text-2xl font-bold">₹32<span className="text-base font-medium text-muted-foreground">/kg</span></p>
        <p className="text-xs text-muted-foreground">Market range ₹29 to ₹35/kg</p>
      </div>
    </div>
  );
}

export function Hero() {
  const { t } = useT();
  const reduce = useReducedMotion();
  return (
    <section className="relative overflow-hidden border-b bg-gradient-to-b from-primary-soft/60 to-background">
      <div className="container grid items-center gap-10 py-14 sm:py-20 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1 text-xs font-medium text-primary">
            <Sparkles className="h-3.5 w-3.5" aria-hidden /> AI grading · smart matching · secure payments
          </span>
          <h1 className="mt-5 max-w-2xl text-4xl font-extrabold leading-[1.08] sm:text-5xl lg:text-6xl">{t("landing.heroTitle")}</h1>
          <p className="mt-5 max-w-xl text-base text-muted-foreground sm:text-lg">{t("landing.heroSub")}</p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg"><Link href="/demo">{t("landing.exploreDemo")} <ArrowRight /></Link></Button>
            <Button asChild size="lg" variant="outline"><Link href="#how">{t("landing.seeHow")}</Link></Button>
          </div>
        </div>
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className="flex justify-center lg:justify-end"
        >
          <GradePreview />
        </motion.div>
      </div>
    </section>
  );
}
