import { api } from "./client";
import type {
  AdminAnalyticsDto, ApprovalDto, AuditLogDto, FlaggedActivityDto, ListingDto, NotificationDto, OrderDto, UserDto,
} from "@/types";

export const adminApi = {
  analytics: () => api.get<AdminAnalyticsDto>("/admin/analytics"),
  users: () => api.get<UserDto[]>("/admin/users"),
  listings: () => api.get<ListingDto[]>("/admin/listings"),
  transactions: () => api.get<OrderDto[]>("/admin/transactions"),
  risk: () => api.get<FlaggedActivityDto[]>("/admin/risk"),
  approvals: () => api.get<ApprovalDto[]>("/admin/approvals"),
  decide: (id: string, action: "approve" | "reject" | "request_review", note?: string) =>
    api.post<ApprovalDto>(`/admin/approvals/${id}`, { action, note }),
  auditLogs: () => api.get<AuditLogDto[]>("/admin/audit-logs"),
  notifications: () => api.get<NotificationDto[]>("/notifications"),
  markRead: (id: string) => api.post<void>(`/notifications/${id}/read`),
};
