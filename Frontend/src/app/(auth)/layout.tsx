import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { LanguageSwitcher } from "@/components/layout/language-switcher";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="flex items-center justify-between px-4 pb-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-8">
        <Link href="/" aria-label="E-Mandi home"><Logo /></Link>
        <div className="flex"><LanguageSwitcher /><ThemeToggle /></div>
      </header>
      <main id="main-content" tabIndex={-1} className="flex flex-1 items-center justify-center px-4 pb-10">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
