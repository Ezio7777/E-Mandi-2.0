"use client";
import { Shield, ShoppingBasket, Sprout } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDemoLogin } from "@/services/auth";
import { useAppDispatch } from "@/store/hooks";
import { tourStarted } from "@/store/slices/tour.slice";
import { useT } from "@/lib/i18n";
import type { Role } from "@/types";

const items = [
  { role: "farmer", key: "auth.tryDemoFarmer", Icon: Sprout },
  { role: "buyer", key: "auth.tryDemoBuyer", Icon: ShoppingBasket },
  { role: "admin", key: "auth.tryDemoAdmin", Icon: Shield },
] as const;

/** One tap: real backend demo login, then the guided tour for that role starts. */
export function DemoButtons({ startTour = true, layout = "row" }: { startTour?: boolean; layout?: "row" | "stack" }) {
  const demo = useDemoLogin();
  const dispatch = useAppDispatch();
  const { t } = useT();
  // A deep link (?next=…) wins over the guided tour: don't yank the user off the page they asked for.
  // The tour stays one tap away from the help icon in the header.
  const go = (role: Role) =>
    demo.mutate(role, {
      onSuccess: () => {
        const hasNext = new URLSearchParams(window.location.search).has("next");
        if (startTour && !hasNext) dispatch(tourStarted(role));
      },
    });

  return (
    <div className="space-y-2">
      <div className={layout === "row" ? "grid gap-2 sm:grid-cols-3" : "grid gap-2"}>
        {items.map(({ role, key, Icon }) => (
          <Button key={role} variant={role === "farmer" ? "default" : "outline"} className="h-auto min-h-touch justify-center whitespace-normal py-2.5 text-center leading-tight" onClick={() => go(role)} loading={demo.isPending && demo.variables === role} disabled={demo.isPending}>
            <Icon /> {t(key)}
          </Button>
        ))}
      </div>
      {demo.isError && <p role="alert" className="text-sm text-danger">{demo.error.message}</p>}
    </div>
  );
}
