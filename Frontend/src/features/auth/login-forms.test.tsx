import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Provider } from "react-redux";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { makeStore } from "@/store";
import { LoginForms } from "./login-forms";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

function setup() {
  return render(
    <Provider store={makeStore()}>
      <QueryClientProvider client={new QueryClient()}>
        <LoginForms />
      </QueryClientProvider>
    </Provider>,
  );
}

describe("LoginForms", () => {
  it("shows validation errors and blocks submit on empty form", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: /log in/i }));
    expect(await screen.findByText(/enter your email/i)).toBeInTheDocument();
    expect(screen.getByText(/enter your password/i)).toBeInTheDocument();
  });
  it("switches to phone OTP", async () => {
    setup();
    await userEvent.click(screen.getByRole("tab", { name: /phone otp/i }));
    expect(screen.getByLabelText(/phone number/i)).toBeInTheDocument();
  });
});
