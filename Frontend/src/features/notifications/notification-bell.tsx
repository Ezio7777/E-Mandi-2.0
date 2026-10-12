"use client";
import { Bell } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useMarkNotificationRead, useNotifications } from "@/services/notifications";
import { formatDate } from "@/utils/format";

export function NotificationBell() {
  const { data } = useNotifications();
  const markRead = useMarkNotificationRead();
  const unread = data?.filter((n) => !n.read).length ?? 0;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="relative" aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}>
          <Bell />
          {unread > 0 && <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-danger" aria-hidden />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="px-3 py-2 text-xs text-muted-foreground">Notifications</DropdownMenuLabel>
        {!data?.length && <p className="px-3 py-4 text-sm text-muted-foreground">You&apos;re all caught up.</p>}
        {data?.slice(0, 6).map((n) => (
          <DropdownMenuItem key={n.id} className="flex-col items-start gap-0.5" onSelect={() => !n.read && markRead.mutate(n.id)}>
            <span className={n.read ? "" : "font-semibold"}>{n.title}</span>
            <span className="text-xs text-muted-foreground">{formatDate(n.at, true)}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
