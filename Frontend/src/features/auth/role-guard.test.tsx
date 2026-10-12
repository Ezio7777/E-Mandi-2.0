import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const nav = vi.hoisted(() => ({ replace: vi.fn(), pathname: "/farmer/orders" }));
const session = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: nav.replace }), usePathname: () => nav.pathname }));
vi.mock("@/services/auth", () => ({ useSession: () => session.value }));

import { RoleGuard } from "./role-guard";

const farmer = { id: "1", name: "Ravi", role: "farmer" as const };

beforeEach(() => { nav.replace.mockClear(); });

describe("RoleGuard", () => {
  it("shows the loading screen while the session is being checked", () => {
    session.value = { isPending: true, isError: false, data: undefined };
    render(<RoleGuard role="farmer"><p>secret</p></RoleGuard>);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("renders children for the matching role", () => {
    session.value = { isPending: false, isError: false, data: farmer };
    render(<RoleGuard role="farmer"><p>secret</p></RoleGuard>);
    expect(screen.getByText("secret")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("sends an unauthenticated visitor to login and remembers where they were going", async () => {
    session.value = { isPending: false, isError: true, data: undefined };
    render(<RoleGuard role="farmer"><p>secret</p></RoleGuard>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?next=%2Ffarmer%2Forders"));
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("redirects a user with the wrong role to their own home and never shows the page", async () => {
    session.value = { isPending: false, isError: false, data: { ...farmer, role: "buyer" } };
    render(<RoleGuard role="farmer"><p>secret</p></RoleGuard>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/buyer/marketplace"));
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });
});
