import type { Metadata, Viewport } from "next";
import { Inter, Plus_Jakarta_Sans, Noto_Sans_Devanagari, Noto_Sans_Kannada } from "next/font/google";
import "./globals.css";
import { cn } from "@/utils/cn";
import { Providers } from "@/providers";

const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const display = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-display", display: "swap" });
const hindi = Noto_Sans_Devanagari({ subsets: ["devanagari"], variable: "--font-hindi", display: "swap" });
const kannada = Noto_Sans_Kannada({ subsets: ["kannada"], variable: "--font-kannada", display: "swap" });

export const metadata: Metadata = {
  title: { default: "E-Mandi | Farm-to-market, made trustworthy", template: "%s | E-Mandi" },
  description: "E-Mandi connects farmers and buyers with AI crop grading, fair price guidance, smart matching, and a transparent transaction flow.",
  applicationName: "E-Mandi",
  icons: { icon: "/icons/favicon.svg" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0b0f0c" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={cn(sans.variable, display.variable, hindi.variable, kannada.variable, "min-h-dvh bg-background font-sans text-foreground antialiased")}>
        <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground">
          Skip to main content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
