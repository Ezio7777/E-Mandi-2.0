import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Provider } from "react-redux";
import { makeStore } from "@/store";
import { localeChanged } from "@/store/slices/theme.slice";

const state = vi.hoisted(() => ({ query: {} as Record<string, unknown> }));
vi.mock("@/services/orders", () => ({ usePayments: () => state.query }));

import { PaymentList } from "./payment-list";

const renderIn = (locale: "en" | "hi" | "kn") => {
  const store = makeStore();
  store.dispatch(localeChanged(locale));
  return render(<Provider store={store}><PaymentList /></Provider>);
};

const row = { orderId: "o1", provider: "razorpay-test", providerOrderId: "po_1", amount: 16000, currency: "INR", status: "success" };

describe("PaymentList localisation and states", () => {
  it("renders column headers in the selected language", () => {
    state.query = { isPending: false, isError: false, data: [row] };
    renderIn("hi");
    expect(screen.getAllByText("राशि").length).toBeGreaterThan(0);
    expect(screen.queryByText("Amount")).not.toBeInTheDocument();
  });

  it("renders the empty state in Kannada", () => {
    state.query = { isPending: false, isError: false, data: [] };
    renderIn("kn");
    expect(screen.getByText("ಇನ್ನೂ ಪಾವತಿಗಳಿಲ್ಲ")).toBeInTheDocument();
  });

  it("shows an error with a retry button instead of a blank screen", () => {
    state.query = { isPending: false, isError: true, error: new Error("Boom"), refetch: vi.fn() };
    renderIn("en");
    expect(screen.getByRole("alert")).toHaveTextContent("Boom");
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("shows a loading skeleton while pending", () => {
    state.query = { isPending: true };
    const { container } = renderIn("en");
    expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  });
});
