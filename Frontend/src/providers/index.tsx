"use client";
import { ReduxProvider } from "./redux-provider";
import { QueryProvider } from "./query-provider";
import { ThemeProvider } from "./theme-provider";
import { LocaleSync } from "./locale-sync";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/feedback/toaster";
import { TourProvider } from "@/features/tour/tour-provider";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ReduxProvider>
      <ThemeProvider>
        <QueryProvider>
          <TooltipProvider delayDuration={200}>
            <LocaleSync />
            <TourProvider>{children}</TourProvider>
            <Toaster />
          </TooltipProvider>
        </QueryProvider>
      </ThemeProvider>
    </ReduxProvider>
  );
}
