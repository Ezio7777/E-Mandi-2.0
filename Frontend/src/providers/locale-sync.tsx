"use client";
import { useEffect } from "react";
import { useAppSelector } from "@/store/hooks";

/** Keeps <html lang> in sync so fonts and screen readers follow the UI language. */
export function LocaleSync() {
  const locale = useAppSelector((s) => s.theme.locale);
  useEffect(() => { document.documentElement.lang = locale; }, [locale]);
  return null;
}
