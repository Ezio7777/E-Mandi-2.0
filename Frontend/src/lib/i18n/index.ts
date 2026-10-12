"use client";

import { useCallback } from "react";
import { useAppSelector } from "@/store/hooks";
import { en, type Dictionary, type DictionaryShape } from "./dictionaries/en";
import { hi } from "./dictionaries/hi";
import { kn } from "./dictionaries/kn";
import type { Locale } from "@/types";

export const dictionaries: Record<Locale, Dictionary> = { en, hi, kn };
export const localeLabels: Record<Locale, string> = { en: "English", hi: "हिन्दी", kn: "ಕನ್ನಡ" };

type Path<T> = T extends string ? never : {
  [K in keyof T & string]: T[K] extends string ? `${K}` | `${K}.${never}` : `${K}.${Path<T[K]>}`;
}[keyof T & string];
export type TranslationKey = Path<DictionaryShape>;

export function translate(locale: Locale, key: TranslationKey): string {
  const lookup = (d: unknown) => key.split(".").reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], d);
  const v = lookup(dictionaries[locale]) ?? lookup(en);
  return typeof v === "string" ? v : key;
}

/** Typed translation hook. Falls back to English if a key is missing. */
export function useT() {
  const locale = useAppSelector((s) => s.theme.locale);
  const t = useCallback((key: TranslationKey) => translate(locale, key), [locale]);
  return { t, locale };
}
