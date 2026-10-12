"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ordersApi, paymentsApi, adminApi, matchingApi, gradingApi } from "@/lib/api";
import { queryKeys } from "@/lib/query/keys";
import { useRealtime } from "@/hooks/use-realtime";
import type { CreateRequirementInput, OrderDto } from "@/types";

export const useOrders = () => useQuery({ queryKey: queryKeys.orders.all, queryFn: ordersApi.list });

/** Live order updates over WebSocket; falls back to the normal cached query if the socket is unavailable. */
export function useOrder(id: string) {
  const qc = useQueryClient();
  useRealtime<OrderDto>(`/ws/orders/${id}`, (o) => qc.setQueryData(queryKeys.orders.detail(id), o));
  return useQuery({ queryKey: queryKeys.orders.detail(id), queryFn: () => ordersApi.byId(id) });
}

export function useCreateOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { listingId: string; quantityKg: number }) => ordersApi.create(v.listingId, v.quantityKg),
    onSuccess: () => void qc.invalidateQueries({ queryKey: queryKeys.orders.all }),
  });
}
export function useConfirmOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ordersApi.confirm(id),
    onSuccess: (o) => { qc.setQueryData(queryKeys.orders.detail(o.id), o); void qc.invalidateQueries({ queryKey: queryKeys.orders.all }); },
  });
}

export const usePayments = () => useQuery({ queryKey: queryKeys.payments.all, queryFn: paymentsApi.list });
export const usePaymentStatus = (orderId: string, poll = false) =>
  useQuery({ queryKey: queryKeys.payments.status(orderId), queryFn: () => paymentsApi.status(orderId), refetchInterval: poll ? 2500 : false });
export function useInitiatePayment() {
  return useMutation({ mutationFn: (orderId: string) => paymentsApi.initiate(orderId) });
}
export function useConfirmPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { orderId: string; payload: Record<string, string> }) => paymentsApi.confirm(v.orderId, v.payload),
    onSuccess: (_d, v) => {
      void qc.invalidateQueries({ queryKey: queryKeys.orders.detail(v.orderId) });
      void qc.invalidateQueries({ queryKey: queryKeys.payments.all });
    },
  });
}

export const useRequirements = () => useQuery({ queryKey: queryKeys.matching.requirements, queryFn: matchingApi.requirements });
export const useMatches = (requirementId?: string, poll = false) =>
  useQuery({ queryKey: queryKeys.matching.matches(requirementId), queryFn: () => matchingApi.matches(requirementId), refetchInterval: poll ? 2000 : false });
export function useCreateRequirement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: CreateRequirementInput) => matchingApi.createRequirement(i),
    onSuccess: () => void qc.invalidateQueries({ queryKey: queryKeys.matching.requirements }),
  });
}

export const useAdminAnalytics = () => useQuery({ queryKey: queryKeys.admin.analytics, queryFn: adminApi.analytics });
export const useAdminUsers = () => useQuery({ queryKey: queryKeys.admin.users, queryFn: adminApi.users });
export const useAdminListings = () => useQuery({ queryKey: queryKeys.admin.listings, queryFn: adminApi.listings });
export const useAdminTransactions = () => useQuery({ queryKey: queryKeys.admin.transactions, queryFn: adminApi.transactions });
export const useAdminRisk = () => useQuery({ queryKey: queryKeys.admin.risk, queryFn: adminApi.risk });
export const useAdminApprovals = () => useQuery({ queryKey: queryKeys.admin.approvals, queryFn: adminApi.approvals });
export const useAdminAuditLogs = () => useQuery({ queryKey: queryKeys.admin.auditLogs, queryFn: adminApi.auditLogs });
export const useGradingQueue = () => useQuery({ queryKey: queryKeys.grading.queue, queryFn: gradingApi.queue });

export function useDecideApproval() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { id: string; action: "approve" | "reject" | "request_review"; note?: string }) => adminApi.decide(v.id, v.action, v.note),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.admin.approvals });
      void qc.invalidateQueries({ queryKey: queryKeys.admin.auditLogs });
    },
  });
}
