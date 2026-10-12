import type { ListingFilters } from "@/types";

export const queryKeys = {
  session: ["session"] as const,
  listings: {
    all: ["listings"] as const,
    list: (f: ListingFilters) => ["listings", "list", f] as const,
    mine: ["listings", "mine"] as const,
    detail: (id: string) => ["listings", "detail", id] as const,
  },
  dashboard: { farmer: ["dashboard", "farmer"] as const },
  orders: {
    all: ["orders"] as const,
    detail: (id: string) => ["orders", id] as const,
  },
  payments: { all: ["payments"] as const, status: (orderId: string) => ["payments", orderId] as const },
  grading: { job: (id: string) => ["grading", id] as const, queue: ["grading", "queue"] as const },
  pricing: (crop: string, grade: string, location: string) => ["pricing", crop, grade, location] as const,
  matching: { requirements: ["requirements"] as const, matches: (id?: string) => ["matches", id ?? "all"] as const },
  admin: {
    analytics: ["admin", "analytics"] as const,
    users: ["admin", "users"] as const,
    listings: ["admin", "listings"] as const,
    transactions: ["admin", "transactions"] as const,
    risk: ["admin", "risk"] as const,
    approvals: ["admin", "approvals"] as const,
    auditLogs: ["admin", "audit-logs"] as const,
  },
  notifications: ["notifications"] as const,
};
