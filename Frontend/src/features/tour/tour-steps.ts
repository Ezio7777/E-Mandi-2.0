import type { Role } from "@/types";

export interface TourStep {
  id: string;
  /** Route to navigate to before showing this step */
  route?: string;
  /** Value of the data-tour attribute to spotlight. Missing target → centered card. */
  target?: string;
  /** Used when `target` isn't on screen (e.g. wizard step not reached, empty data). */
  fallbackTarget?: string;
  title: string;
  body: string;
  /** "Next recommended action" line */
  nextAction?: string;
}

export const TOURS: Record<Role, TourStep[]> = {
  farmer: [
    { id: "f1", route: "/farmer/dashboard", target: "farmer-stats", title: "Your farm at a glance", body: "Active listings, stock, pending orders and earnings, all in one place.", nextAction: "Open Sell crop" },
    { id: "f2", route: "/farmer/sell", target: "sell-wizard", title: "Sell in a few simple steps", body: "A guided flow: photo, crop, quantity, location, then AI checks quality and suggests a price.", nextAction: "Pick a sample crop" },
    { id: "f3", route: "/farmer/sell", target: "upload-zone", fallbackTarget: "sell-wizard", title: "Upload or try a sample", body: "Drop photos, use your phone camera, or tap a sample crop to see the full flow instantly.", nextAction: "Continue to AI grading" },
    { id: "f4", route: "/farmer/sell", target: "grading-card", fallbackTarget: "sell-wizard", title: "AI grading you can read", body: "After you add photos and details, this step shows grade, confidence, defect percentage and the reason. Low confidence is flagged for manual review.", nextAction: "See the price suggestion" },
    { id: "f5", route: "/farmer/sell", target: "price-card", fallbackTarget: "sell-wizard", title: "A fair price, explained", body: "Next comes the suggested price, market range and trend, with the data source when available.", nextAction: "Review and publish" },
    { id: "f6", route: "/farmer/listings", target: "nav-listings", fallbackTarget: "nav-dashboard", title: "Your published listings", body: "Track stock and status here. Buyers see your listing in the marketplace.", nextAction: "Check your orders" },
    { id: "f7", route: "/farmer/orders", target: "nav-orders", title: "Orders and payments", body: "Every order has a clear timeline from reservation to completion.", nextAction: "You're done!" },
  ],
  buyer: [
    { id: "b1", route: "/buyer/marketplace", target: "marketplace-filters", title: "Search and filter", body: "Filter by crop, grade, price, quantity and location. Sort to find the best fit.", nextAction: "Open a listing" },
    { id: "b2", route: "/buyer/requirements/new", target: "requirement-form", title: "Tell us what you need", body: "Post a requirement like '500 kg Grade A tomatoes in Bangalore by tomorrow'.", nextAction: "See your matches" },
    { id: "b3", route: "/buyer/matches", target: "nav-matches", title: "Matches with reasons", body: "Every match shows exactly why: grade, quantity, location, price and availability.", nextAction: "Place an order" },
    { id: "b4", route: "/buyer/orders", target: "nav-marketplace", title: "Order, pay, track", body: "Pay securely and follow the transaction timeline until delivery is complete.", nextAction: "You're done!" },
  ],
  admin: [
    { id: "a1", route: "/admin/analytics", target: "admin-metrics", title: "Marketplace health", body: "Users, listings, transactions, value and flagged activity at a glance.", nextAction: "Review flagged activity" },
    { id: "a2", route: "/admin/risk", target: "nav-risk", title: "Flagged for review", body: "Suspicious listings, low-confidence grading and repeated failed payments, with severity and a recommended action.", nextAction: "Open approvals" },
    { id: "a3", route: "/admin/approvals", target: "nav-approvals", title: "Human in the loop", body: "Sensitive actions need admin approval. Approve, reject or request a review, with the reason recorded.", nextAction: "Check the audit log" },
    { id: "a4", route: "/admin/audit-logs", target: "nav-audit", title: "Everything is on record", body: "Every decision is written to the audit log with actor, action and time.", nextAction: "You're done!" },
  ],
};
