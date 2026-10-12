import type {
  ApprovalDto, AuditLogDto, FlaggedActivityDto, Grade, GradingResultDto, ListingDto, NotificationDto, OrderDto, OrderStatus,
  PaymentStatus, PriceSuggestionDto, RequirementDto, Role, UserDto,
} from "@/types";

const DAY = 86_400_000;
const MIN = 60_000;
export const isoAt = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();
export const dateOnly = (offsetDays: number) => new Date(Date.now() + offsetDays * DAY).toISOString().slice(0, 10);

export const DEMO_USERS: Record<Role, UserDto> = {
  farmer: { id: "u-farmer", name: "Ravi Kumar", role: "farmer", phone: "+919876543210", location: "Hosur, Tamil Nadu", isDemo: true },
  buyer: { id: "u-buyer", name: "Fresh Basket Pvt Ltd", role: "buyer", email: "buyer@demo.emandi.app", location: "Bengaluru", isDemo: true },
  admin: { id: "u-admin", name: "Admin Demo", role: "admin", email: "admin@demo.emandi.app", isDemo: true },
};

export const CROPS = ["tomato", "potato", "onion", "cabbage"] as const;
export type CropKey = (typeof CROPS)[number];
export const cropKey = (name: string): CropKey | null => CROPS.find((c) => name.toLowerCase().includes(c)) ?? null;
export const cropImage = (name: string) => ({ id: `img-${cropKey(name) ?? "tomato"}`, objectKey: `samples/${cropKey(name) ?? "tomato"}`, url: `/demo-crops/${cropKey(name) ?? "tomato"}.svg` });

/** Deterministic AI results so the demo tells a story: cabbage is deliberately low-confidence (manual review). */
export function gradeFor(crop: string): Omit<GradingResultDto, "jobId" | "gradedAt"> {
  switch (cropKey(crop)) {
    case "potato":
      return { grade: "B", confidence: 0.88, defectPercent: 6.1, explanation: "Some skin scuffing and a few green patches. Size is consistent across the lot.", issues: ["Skin scuffing", "Green patches"], provider: "Gemini Vision (demo)", manualReviewRecommended: false };
    case "onion":
      return { grade: "A", confidence: 0.91, defectPercent: 3.2, explanation: "Dry, firm bulbs with tight skins. A few have minor neck sprouting.", issues: ["Minor sprouting"], provider: "Gemini Vision (demo)", manualReviewRecommended: false };
    case "cabbage":
      return { grade: "C", confidence: 0.58, defectPercent: 14, explanation: "Outer leaves show damage and uneven colour. The photo is also slightly blurry, so confidence is low.", issues: ["Leaf damage", "Uneven colour", "Blurry photo"], provider: "Gemini Vision (demo)", manualReviewRecommended: true };
    default:
      return { grade: "A", confidence: 0.94, defectPercent: 2.5, explanation: "Minor surface bruising on a few fruits. Colour and firmness are consistent across the lot.", issues: ["Surface bruising", "Slight colour variation"], provider: "Gemini Vision (demo)", manualReviewRecommended: false };
  }
}

const BASE: Record<CropKey, { price: number; lo: number; hi: number; trend: PriceSuggestionDto["trend"]; note: string; market: string }> = {
  tomato: { price: 32, lo: 29, hi: 35, trend: "up", note: "Arrivals at Kolar APMC are lower than last week, supporting a slightly higher price.", market: "Kolar APMC" },
  potato: { price: 18, lo: 16, hi: 20, trend: "stable", note: "Prices have been steady for two weeks with normal arrivals.", market: "Hassan APMC" },
  onion: { price: 24, lo: 21, hi: 27, trend: "down", note: "Fresh arrivals from Nashik are pushing prices down slightly.", market: "Nashik APMC" },
  cabbage: { price: 12, lo: 10, hi: 14, trend: "stable", note: "Local supply is plentiful, keeping prices flat.", market: "Mysuru APMC" },
};
export function priceFor(crop: string, grade: Grade): PriceSuggestionDto {
  const b = BASE[cropKey(crop) ?? "tomato"];
  const f = grade === "A" ? 1 : grade === "B" ? 0.9 : 0.78;
  const r = (n: number) => Math.round(n * f);
  return { suggested: r(b.price), rangeMin: r(b.lo), rangeMax: r(b.hi), referencePrice: r(b.price) - 1, trend: b.trend, explanation: `${b.note} Adjusted for Grade ${grade}.`, source: `Agmarknet, ${b.market} (demo data)` };
}

const listing = (id: string, crop: string, grade: Grade, qty: number, price: number, loc: string, farmer: string, status: ListingDto["status"] = "active", verified = true): ListingDto => ({
  id, crop: crop[0]!.toUpperCase() + crop.slice(1), grade, quantityKg: qty, pricePerKg: price, location: loc, farmerName: farmer, farmerVerified: verified,
  images: [cropImage(crop)], status, availableFrom: dateOnly(-1), createdAt: isoAt(-3 * DAY),
});

const ORDER: OrderStatus[] = ["created", "reserved", "payment_confirmed", "farmer_confirmed", "fulfilled", "completed"];
export function makeOrder(id: string, l: ListingDto, qty: number, status: OrderStatus, pay: PaymentStatus, buyerName: string, createdMs: number): OrderDto {
  const upTo = Math.max(ORDER.indexOf(status), status === "disputed" ? 2 : 0);
  return {
    id, transactionId: pay === "success" || pay === "disputed" ? `TXN-${id.toUpperCase()}-${String(createdMs).slice(-5)}` : undefined,
    listing: l, farmerName: l.farmerName, buyerName, quantityKg: qty, pricePerKg: l.pricePerKg, totalAmount: qty * l.pricePerKg,
    status, paymentStatus: pay, createdAt: new Date(createdMs).toISOString(),
    timeline: ORDER.slice(0, upTo + 1).map((step, i) => ({ step, at: new Date(createdMs + i * 25 * MIN).toISOString() })),
  };
}

export interface DemoApproval extends ApprovalDto { listingId?: string }
export interface DemoRequirement extends RequirementDto { createdMs: number }

export interface DemoDb {
  listings: ListingDto[]; orders: OrderDto[]; requirements: DemoRequirement[]; approvals: DemoApproval[];
  audit: AuditLogDto[]; notifications: NotificationDto[]; risk: FlaggedActivityDto[];
  jobs: Map<string, { startedMs: number; cropName: string }>; seq: number;
}

export function createSeed(): DemoDb {
  const listings = [
    listing("l1", "tomato", "A", 800, 32, "Hosur, Tamil Nadu", "Ravi Kumar"),
    listing("l2", "potato", "B", 1200, 18, "Kolar, Karnataka", "Lakshmi Devi"),
    listing("l3", "onion", "A", 2500, 24, "Nashik, Maharashtra", "Suresh Patil", "pending_review", false),
    listing("l4", "cabbage", "C", 400, 12, "Mysuru, Karnataka", "Anita Rao"),
    listing("l5", "tomato", "B", 600, 27, "Kolar, Karnataka", "Ravi Kumar"),
    listing("l6", "onion", "B", 1800, 21, "Hosur, Tamil Nadu", "Ravi Kumar"),
  ];
  const now = Date.now();
  const buyer = DEMO_USERS.buyer.name;
  const orders = [
    makeOrder("o1", listings[0]!, 500, "payment_confirmed", "success", buyer, now - 2 * DAY),
    makeOrder("o2", listings[0]!, 300, "reserved", "not_started", buyer, now - 3 * 60 * MIN),
    makeOrder("o3", listings[1]!, 700, "completed", "success", buyer, now - 9 * DAY),
    makeOrder("o4", listings[4]!, 200, "disputed", "disputed", buyer, now - 5 * DAY),
  ];
  const requirements: DemoRequirement[] = [{ id: "r1", crop: "Tomato", quantityKg: 500, desiredGrade: "A", destination: "Bangalore", deliveryDate: dateOnly(1), maxBudget: 20000, status: "matched", createdAt: isoAt(-DAY), createdMs: now - DAY }];
  const risk: FlaggedActivityDto[] = [
    { id: "f1", severity: "high", event: "Unusually low bid on 2,500 kg Onion", entity: "Bid #4821 by Buyer B-118", reason: "Bid is 46% below the 30-day reference price for this grade.", recommendedAction: "Review the bid before accepting.", at: isoAt(-40 * MIN) },
    { id: "f2", severity: "medium", event: "Repeated failed payments", entity: "Buyer B-204", reason: "4 failed payment attempts in 20 minutes.", recommendedAction: "Contact the buyer; consider a temporary hold.", at: isoAt(-3 * 60 * MIN) },
    { id: "f3", severity: "low", event: "Low AI grading confidence", entity: "Listing l3 (Onion)", reason: "Grading confidence 58%, below the review threshold.", recommendedAction: "Request manual grading review.", at: isoAt(-DAY) },
    { id: "f4", severity: "medium", event: "Repeated listing changes", entity: "Farmer F-077", reason: "Price edited 9 times in one hour on the same listing.", recommendedAction: "Flagged for review. No action needed unless it continues.", at: isoAt(-2 * DAY) },
  ];
  const approvals: DemoApproval[] = [
    { id: "a1", listingId: "l3", title: "Publish listing: Onion, 2,500 kg", reason: "Low AI confidence (58%). Manual review required before publishing.", status: "pending", history: [{ at: isoAt(-2 * 60 * MIN), actor: "System", action: "flagged for approval" }] },
    { id: "a2", title: "Refund order o4 (₹6,400)", reason: "Buyer dispute: quantity mismatch reported on delivery.", status: "pending", history: [{ at: isoAt(-5 * 60 * MIN), actor: "System", action: "flagged for approval" }] },
    { id: "a3", title: "Verify farmer: Anita Rao", reason: "Identity documents uploaded.", status: "approved", history: [{ at: isoAt(-2 * DAY), actor: "Admin Demo", action: "approved", note: "Documents verified" }] },
  ];
  const audit: AuditLogDto[] = [
    { id: "au1", at: isoAt(-2 * DAY), actor: "Admin Demo", action: "Approved farmer verification", entity: "Anita Rao" },
    { id: "au2", at: isoAt(-DAY), actor: "System", action: "Flagged low-confidence grading", entity: "Listing l3" },
    { id: "au3", at: isoAt(-5 * 60 * MIN), actor: "System", action: "Raised refund approval", entity: "Order o4" },
  ];
  const notifications: NotificationDto[] = [
    { id: "n1", title: "Payment confirmed for order o1", read: false, at: isoAt(-2 * DAY) },
    { id: "n2", title: "Your Tomato listing is live", read: false, at: isoAt(-3 * DAY) },
    { id: "n3", title: "New match found for your Tomato requirement", read: true, at: isoAt(-DAY) },
  ];
  return { listings, orders, requirements, approvals, audit, notifications, risk, jobs: new Map(), seq: 100 };
}
