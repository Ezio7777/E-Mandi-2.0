import {
  BarChart3, Bot, ClipboardCheck, CreditCard, Flag, LayoutDashboard, Leaf, Mic, PackageSearch,
  Receipt, ScrollText, ShieldAlert, ShoppingBasket, Sprout, Store, Target, User, Users, type LucideIcon,
} from "lucide-react";
import type { Role } from "@/types";
import type { TranslationKey } from "@/lib/i18n";

export interface NavItem {
  href: string;
  labelKey: TranslationKey;
  icon: LucideIcon;
  /** shown in the mobile bottom bar (max 5 per role) */
  primary?: boolean;
  tourId?: string;
}

export const NAV: Record<Role, NavItem[]> = {
  farmer: [
    { href: "/farmer/dashboard", labelKey: "nav.dashboard", icon: LayoutDashboard, primary: true, tourId: "nav-dashboard" },
    { href: "/farmer/sell", labelKey: "nav.sellCrop", icon: Sprout, primary: true, tourId: "nav-sell" },
    { href: "/farmer/listings", labelKey: "nav.myListings", icon: Leaf, primary: true, tourId: "nav-listings" },
    { href: "/farmer/orders", labelKey: "nav.orders", icon: PackageSearch, primary: true, tourId: "nav-orders" },
    { href: "/farmer/payments", labelKey: "nav.payments", icon: CreditCard },
    { href: "/farmer/assistant", labelKey: "nav.assistant", icon: Mic, tourId: "nav-assistant" },
    { href: "/farmer/profile", labelKey: "nav.profile", icon: User },
  ],
  buyer: [
    { href: "/buyer/marketplace", labelKey: "nav.marketplace", icon: Store, primary: true, tourId: "nav-marketplace" },
    { href: "/buyer/requirements", labelKey: "nav.requirements", icon: ClipboardCheck, primary: true },
    { href: "/buyer/matches", labelKey: "nav.matches", icon: Target, primary: true, tourId: "nav-matches" },
    { href: "/buyer/orders", labelKey: "nav.orders", icon: ShoppingBasket, primary: true },
    { href: "/buyer/payments", labelKey: "nav.payments", icon: CreditCard },
    { href: "/buyer/profile", labelKey: "nav.profile", icon: User },
  ],
  admin: [
    { href: "/admin/analytics", labelKey: "nav.analytics", icon: BarChart3, primary: true, tourId: "nav-analytics" },
    { href: "/admin/risk", labelKey: "nav.risk", icon: Flag, primary: true, tourId: "nav-risk" },
    { href: "/admin/approvals", labelKey: "nav.approvals", icon: ClipboardCheck, primary: true, tourId: "nav-approvals" },
    { href: "/admin/transactions", labelKey: "nav.transactions", icon: Receipt, primary: true },
    { href: "/admin/users", labelKey: "nav.users", icon: Users },
    { href: "/admin/listings", labelKey: "nav.listings", icon: Leaf },
    { href: "/admin/grading", labelKey: "nav.grading", icon: Bot },
    { href: "/admin/disputes", labelKey: "nav.disputes", icon: ShieldAlert },
    { href: "/admin/audit-logs", labelKey: "nav.auditLogs", icon: ScrollText, tourId: "nav-audit" },
  ],
};

