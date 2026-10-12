import { ROLE_HOME, ROLE_PREFIX } from "@/config/routes";
import type { Role } from "@/types";

/**
 * Returns a same-origin path the user may land on after login, else their role home.
 * Blocks open redirects (//evil.com, https://…, backslashes) and other roles' areas.
 */
export function resolveNext(next: string | null | undefined, role: Role): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return ROLE_HOME[role];
  const prefix = ROLE_PREFIX[role];
  if (next === prefix || next.startsWith(`${prefix}/`)) return next;
  return ROLE_HOME[role];
}
