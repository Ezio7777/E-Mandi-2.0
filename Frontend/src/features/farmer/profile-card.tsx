"use client";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useAppSelector } from "@/store/hooks";

export function ProfileCard() {
  const user = useAppSelector((s) => s.auth.user);
  if (!user) return null;
  const rows = [["Name", user.name], ["Role", user.role], ["Email", user.email ?? "—"], ["Phone", user.phone ?? "—"], ["Location", user.location ?? "—"]];
  return (
    <Card className="max-w-xl p-5">
      <div className="mb-4 flex items-center gap-3">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary-soft font-display text-lg font-bold text-primary" aria-hidden>{user.name.slice(0, 1)}</span>
        <div><p className="font-semibold">{user.name}</p>{user.isDemo && <Badge variant="warning">Demo account</Badge>}</div>
      </div>
      <dl className="divide-y text-sm">{rows.map(([k, v]) => <div key={k} className="flex justify-between gap-4 py-2.5"><dt className="text-muted-foreground">{k}</dt><dd className="text-right font-medium capitalize">{v}</dd></div>)}</dl>
    </Card>
  );
}
