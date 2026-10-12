import { MarketingFooter, MarketingHeader } from "@/features/landing/marketing-chrome";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <MarketingHeader />
      <main id="main-content" tabIndex={-1}>{children}</main>
      <MarketingFooter />
    </>
  );
}
