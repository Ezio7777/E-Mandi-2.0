"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminApi } from "@/lib/api";
import { queryKeys } from "@/lib/query/keys";
import type { NotificationDto } from "@/types";

export const useNotifications = () =>
  useQuery({ queryKey: queryKeys.notifications, queryFn: adminApi.notifications, refetchInterval: 60_000, retry: false });

/** Optimistic: the dot disappears immediately; rolled back if the API rejects. */
export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => adminApi.markRead(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: queryKeys.notifications });
      const prev = qc.getQueryData<NotificationDto[]>(queryKeys.notifications);
      qc.setQueryData<NotificationDto[]>(queryKeys.notifications, (cur) => cur?.map((n) => (n.id === id ? { ...n, read: true } : n)));
      return { prev };
    },
    onError: (_e, _id, ctx) => ctx?.prev && qc.setQueryData(queryKeys.notifications, ctx.prev),
    onSettled: () => void qc.invalidateQueries({ queryKey: queryKeys.notifications }),
  });
}
