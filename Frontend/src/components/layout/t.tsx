"use client";
import { useT, type TranslationKey } from "@/lib/i18n";

/** Inline translated text for server components that can't call useT. */
export function T({ k }: { k: TranslationKey }) {
  const { t } = useT();
  return <>{t(k)}</>;
}
