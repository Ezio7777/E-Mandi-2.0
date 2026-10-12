import { AppShell } from "@/components/layout/app-shell";

export default function FarmerLayout({ children }: { children: React.ReactNode }) {
  return <AppShell role="farmer">{children}</AppShell>;
}
