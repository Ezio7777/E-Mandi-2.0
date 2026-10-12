import { api } from "./client";
import type { OrderDto } from "@/types";

export const ordersApi = {
  list: () => api.get<OrderDto[]>("/orders"),
  byId: (id: string) => api.get<OrderDto>(`/orders/${id}`),
  create: (listingId: string, quantityKg: number) => api.post<OrderDto>("/orders", { listingId, quantityKg }),
  confirm: (id: string) => api.post<OrderDto>(`/orders/${id}/confirm`),
  cancel: (id: string) => api.post<OrderDto>(`/orders/${id}/cancel`),
};
