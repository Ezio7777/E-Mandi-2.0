import type { Role } from "@/types";

export const ROUTES = {
  home: "/",
  howItWorks: "/how-it-works",
  login: "/login",
  demo: "/demo",
} as const;

export const ROLE_HOME: Record<Role, string> = {
  farmer: "/farmer/dashboard",
  buyer: "/buyer/marketplace",
  admin: "/admin/analytics",
};

export const ROLE_PREFIX: Record<Role, string> = { farmer: "/farmer", buyer: "/buyer", admin: "/admin" };
export const AUTH_PAGES = ["/login", "/register", "/demo"];
export const SESSION_COOKIE_HINT = "emandi_session";
