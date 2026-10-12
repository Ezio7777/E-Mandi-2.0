"use client";
import { useT, type TranslationKey } from "@/lib/i18n";

interface Props {
  titleKey: TranslationKey;
  descriptionKey?: TranslationKey;
  actions?: React.ReactNode;
}

export function PageHeader({ titleKey, descriptionKey, actions }: Props) {
  const { t } = useT();
  return (
    <div className="mb-5 flex flex-col gap-3 sm:mb-6 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold sm:text-3xl">{t(titleKey)}</h1>
        {descriptionKey && <p className="mt-1 max-w-2xl text-sm text-muted-foreground sm:text-base">{t(descriptionKey)}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
