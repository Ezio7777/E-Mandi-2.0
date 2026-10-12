import { env } from "@/config/env";
import type { PaymentSessionDto } from "@/types";

/**
 * Provider adapter. The UI never talks to a provider SDK directly.
 * Implement `open` for the chosen sandbox provider (e.g. Razorpay test mode). Only the PUBLIC key is used here.
 * The backend verifies the payment signature and remains the source of truth.
 */
export interface PaymentProviderAdapter {
  open(session: PaymentSessionDto): Promise<Record<string, string>>;
}

export const paymentProvider: PaymentProviderAdapter = {
  async open(session) {
    const key = session.publicKey ?? env.paymentPublicKey;
    if (!key) throw new Error("Payments aren't configured yet. Set NEXT_PUBLIC_PAYMENT_PUBLIC_KEY or return publicKey from /payments/initiate.");
    // TODO(stage 14): load provider checkout script, open widget, resolve with provider response payload.
    // Sandbox fallback so the flow is demonstrable: backend accepts the provider order ID as a test confirmation.
    return { providerOrderId: session.providerOrderId, mode: "sandbox" };
  },
};
