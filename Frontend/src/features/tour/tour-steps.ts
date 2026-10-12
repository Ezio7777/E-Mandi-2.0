import { env } from "@/config/env";
import type { Role } from "@/types";

export interface TourStep {
  id: string;
  /** Route to navigate to before showing this step */
  route?: string;
  /** Value of the data-tour attribute to spotlight. Missing target → centered card. */
  target?: string;
  /** Used when `target` isn't on screen. With `waitMs` it is spotlighted while the real target loads. */
  fallbackTarget?: string;
  /** CSS selector that must exist before the step is shown (e.g. data finished loading). */
  ready?: string;
  /** How long (ms) to wait for `target` before giving up. Default 4000. */
  waitMs?: number;
  /** Ask the Sell wizard to show this step with demo data (0 = photos, 4 = grading, 5 = price, 6 = review). */
  wizard?: { goal: number; sample?: boolean };
  /** Ask a form to fill itself with demo values. */
  fill?: "requirement";
  /** Only meaningful with the built-in demo data (fixed ids), skipped against a real backend. */
  demoOnly?: boolean;
  title: string;
  body: string;
  /** "Next recommended action" line */
  nextAction?: string;
}

export const TOURS: Record<Role, TourStep[]> = {
  farmer: [
    { id: "f1", route: "/farmer/dashboard", target: "farmer-stats", title: "Your farm at a glance", body: "Active listings, stock, pending orders and earnings, all in one place.", nextAction: "Open Sell crop" },
    { id: "f2", route: "/farmer/sell", target: "sell-wizard", title: "Sell in a few simple steps", body: "A guided flow: photo, crop, quantity, location, then AI checks quality and suggests a price.", nextAction: "Pick a sample crop" },
    { id: "f3", route: "/farmer/sell", target: "upload-zone", wizard: { goal: 0, sample: true }, ready: '[data-upload-ready="true"]', title: "Start with a photo", body: "Upload photos, use your phone camera, or tap a sample crop. We picked Tomato for you.", nextAction: "Let the AI grade it" },
    { id: "f4", route: "/farmer/sell", target: "grade-result", fallbackTarget: "grading-card", waitMs: 12000, wizard: { goal: 4 }, title: "AI grading you can read", body: "We filled in 800 kg from Hosur. The AI returns a grade, its confidence, the defect percentage and the reason. Low confidence is flagged for manual review.", nextAction: "See the price suggestion" },
    { id: "f5", route: "/farmer/sell", target: "price-card", ready: '[data-price-ready="true"]', waitMs: 8000, wizard: { goal: 5 }, title: "A fair price, explained", body: "The suggested price with the market range, trend and data source. You can change it before publishing.", nextAction: "Review and publish" },
    { id: "f6", route: "/farmer/sell", target: "review-card", wizard: { goal: 6 }, title: "Review, then publish", body: "Everything in one summary. One tap publishes it to buyers. We won't publish anything during the tour.", nextAction: "See your listings" },
    { id: "f7", route: "/farmer/listings", target: "listing-card", fallbackTarget: "nav-listings", title: "Your listings", body: "Track stock and status here. Buyers see active listings in the marketplace.", nextAction: "Check your orders" },
    { id: "f8", route: "/farmer/orders", target: "orders-list", fallbackTarget: "nav-orders", title: "Orders and payments", body: "Every order has a clear timeline from reservation to completion.", nextAction: "You're done!" },
  ],
  buyer: [
    { id: "b1", route: "/buyer/marketplace", target: "marketplace-filters", title: "Search and filter", body: "Filter by crop, grade, price, quantity and location. Sort to find the best fit.", nextAction: "Post a requirement" },
    { id: "b2", route: "/buyer/requirements/new", target: "requirement-form", fill: "requirement", title: "Tell us what you need", body: "Describe the lot you want. We filled in 500 kg of Grade A tomatoes for Bangalore.", nextAction: "See your matches" },
    { id: "b3", route: "/buyer/matches", target: "match-card", fallbackTarget: "nav-matches", title: "Matches with reasons", body: "Every match shows exactly why: grade, quantity, location, price and availability, not just a score.", nextAction: "Open your orders" },
    { id: "b4", route: "/buyer/orders", target: "orders-list", fallbackTarget: "nav-orders", title: "Your orders", body: "Every purchase, with its status and payment state.", nextAction: "Open an order to pay" },
    { id: "b5", route: "/buyer/orders/o2", target: "checkout-panel", fallbackTarget: "order-timeline", demoOnly: true, title: "Pay and track", body: "Secure checkout (test mode) and a live timeline from reservation to completion.", nextAction: "You're done!" },
  ],
  admin: [
    { id: "a1", route: "/admin/analytics", target: "admin-metrics", title: "Marketplace health", body: "Users, listings, transactions, value and flagged activity at a glance.", nextAction: "Review flagged activity" },
    { id: "a2", route: "/admin/risk", target: "risk-list", fallbackTarget: "nav-risk", title: "Flagged for review", body: "Suspicious listings, low-confidence grading and repeated failed payments, each with a severity and a recommended action.", nextAction: "Open approvals" },
    { id: "a3", route: "/admin/approvals", target: "approvals-list", fallbackTarget: "nav-approvals", title: "Human in the loop", body: "Sensitive actions need admin approval. Approve, reject or request a review, with the reason recorded.", nextAction: "Check the audit log" },
    { id: "a4", route: "/admin/audit-logs", target: "audit-table", fallbackTarget: "nav-audit", title: "Everything is on record", body: "Every decision is written to the audit log with actor, action and time.", nextAction: "You're done!" },
  ],
};

/** Steps for a role, minus the ones that only make sense with the built-in demo data. */
export const tourSteps = (role: Role): TourStep[] => TOURS[role].filter((s) => env.demoMode || !s.demoOnly);
