import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LogoMark } from "@/components/brand/logo-mark";

export default function NotFound() {
  return (
    <main id="main-content" className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
      <LogoMark className="h-14 w-14" />
      <h1 className="text-3xl font-bold">Page not found</h1>
      <p className="max-w-sm text-muted-foreground">That page doesn&apos;t exist or has moved.</p>
      <Button asChild><Link href="/">Back to home</Link></Button>
    </main>
  );
}
