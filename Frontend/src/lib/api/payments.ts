import { api } from "./client";
import type { PaymentSessionDto } from "@/types";

export const paymentsApi = {
  initiate: (orderId: string) => api.post<PaymentSessionDto>("/payments/initiate", { orderId }),
  status: (orderId: string) => api.get<PaymentSessionDto>(`/payments/${orderId}`),
  /** Called after the provider widget returns; backend verifies the signature server-side. */
  confirm: (orderId: string, providerPayload: Record<string, string>) =>
    api.post<PaymentSessionDto>("/payments/confirm", { orderId, ...providerPayload }),
  list: () => api.get<PaymentSessionDto[]>("/payments"),
};
