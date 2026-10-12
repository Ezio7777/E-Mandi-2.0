import { ApiError } from "@/lib/api/errors";
import type {
  AdminAnalyticsDto, ApprovalDto, FarmerDashboardDto, GradingJobDto, ImageDto, ListingDto, ListingFilters, MatchDto, MatchReasonDto,
  OrderDto, PaymentSessionDto, Role, UserDto, VoiceReplyDto,
} from "@/types";
import {
  CROPS, DEMO_USERS, cropImage, createSeed, dateOnly, gradeFor, isoAt, makeOrder, priceFor, type DemoApproval, type DemoDb, type DemoRequirement,
} from "./seed";

type Query = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;

const SESSION_KEY = "emandi-demo-session";
let db: DemoDb | null = null;
const getDb = () => (db ??= createSeed());
/** Test helper: start from a fresh seed. */
export function resetDemoDb() { db = null; }

function readRole(): Role | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    const r = raw ? (JSON.parse(raw) as { role?: Role }).role : undefined;
    return r === "farmer" || r === "buyer" || r === "admin" ? r : null;
  } catch { return null; }
}
function writeRole(role: Role | null) {
  try {
    if (role) window.localStorage.setItem(SESSION_KEY, JSON.stringify({ role }));
    else window.localStorage.removeItem(SESSION_KEY);
  } catch { /* storage unavailable */ }
}

const str = (v: unknown, d = "") => (typeof v === "string" ? v : d);
const num = (v: unknown, d = 0) => { const n = typeof v === "number" ? v : Number(v); return Number.isFinite(n) ? n : d; };
const q = (query: Query, k: string) => (query[k] === undefined || query[k] === null || query[k] === "" ? undefined : String(query[k]));

function user(): UserDto {
  const r = readRole();
  if (!r) throw new ApiError(401, "Not signed in");
  return DEMO_USERS[r];
}
function need(u: UserDto, ...roles: Role[]) {
  if (!roles.includes(u.role)) throw new ApiError(403, "You don't have access to this");
}
const notFound = (what: string) => new ApiError(404, `${what} not found`);

/* ---------------- matching ---------------- */
const NEAR_BANGALORE = ["bangalore", "bengaluru", "kolar", "hosur", "mysuru", "tumkur", "hassan"];
const gradeRank = { A: 0, B: 1, C: 2 } as const;

export function matchListing(req: DemoRequirement, l: ListingDto): MatchDto | null {
  if (l.status !== "active" || l.crop.toLowerCase() !== req.crop.trim().toLowerCase()) return null;
  const gradeOk = gradeRank[l.grade] <= gradeRank[req.desiredGrade];
  const qtyOk = l.quantityKg >= req.quantityKg;
  const dest = req.destination.toLowerCase();
  const place = l.location.toLowerCase();
  const locOk = NEAR_BANGALORE.some((c) => dest.includes(c)) ? NEAR_BANGALORE.some((c) => place.includes(c)) : place.split(/[ ,]+/).some((t) => t.length > 2 && dest.includes(t));
  const total = l.pricePerKg * req.quantityKg;
  const priceOk = total <= req.maxBudget;
  const availOk = !l.availableFrom || l.availableFrom <= req.deliveryDate;
  const reasons: MatchReasonDto[] = [
    { factor: "grade", matched: gradeOk, detail: gradeOk ? `Grade ${l.grade}${l.grade === req.desiredGrade ? " as requested" : ", better than requested"}` : `Grade ${l.grade}, you asked for ${req.desiredGrade}` },
    { factor: "quantity", matched: qtyOk, detail: qtyOk ? `${l.quantityKg.toLocaleString("en-IN")} kg available, you need ${req.quantityKg.toLocaleString("en-IN")} kg` : `Only ${l.quantityKg.toLocaleString("en-IN")} kg available, you need ${req.quantityKg.toLocaleString("en-IN")} kg` },
    { factor: "location", matched: locOk, detail: locOk ? `${l.location} is close to ${req.destination}` : `${l.location} is far from ${req.destination}` },
    { factor: "price", matched: priceOk, detail: priceOk ? `₹${l.pricePerKg}/kg (₹${total.toLocaleString("en-IN")}) is inside your budget` : `₹${total.toLocaleString("en-IN")} is over your ₹${req.maxBudget.toLocaleString("en-IN")} budget` },
    { factor: "availability", matched: availOk, detail: availOk ? "Available by your delivery date" : "Not available until after your delivery date" },
  ];
  const w = [0.3, 0.25, 0.2, 0.15, 0.1];
  const score = reasons.reduce((s, r, i) => s + (r.matched ? w[i]! : 0), 0);
  return { listingId: l.id, score: Math.round(score * 100) / 100, listing: l, reasons };
}

/* ---------------- helpers ---------------- */
const visibleOrders = (u: UserDto, d: DemoDb) => (u.role === "admin" ? d.orders : u.role === "buyer" ? d.orders.filter((o) => o.buyerName === u.name) : d.orders.filter((o) => o.farmerName === u.name));
const paymentSession = (o: OrderDto): PaymentSessionDto => ({ orderId: o.id, provider: "razorpay-test", providerOrderId: `order_${o.id}`, amount: o.totalAmount, currency: "INR", publicKey: "rzp_test_demo", status: o.paymentStatus });
const months = () => Array.from({ length: 6 }, (_, i) => new Date(Date.now() - (5 - i) * 30 * 86_400_000).toLocaleString("en-US", { month: "short" }));
const series = (vals: number[]) => months().map((label, i) => ({ label, value: vals[i]! }));

function addNotification(d: DemoDb, title: string) { d.notifications.unshift({ id: `n${++d.seq}`, title, read: false, at: isoAt(0) }); }
function addAudit(d: DemoDb, actor: string, action: string, entity: string) { d.audit.unshift({ id: `au${++d.seq}`, at: isoAt(0), actor, action, entity }); }

function farmerDashboard(u: UserDto, d: DemoDb): FarmerDashboardDto {
  const mine = d.listings.filter((l) => l.farmerName === u.name);
  const active = mine.filter((l) => l.status === "active");
  const orders = d.orders.filter((o) => o.farmerName === u.name);
  const grades = { A: 0, B: 0, C: 0 };
  mine.forEach((l) => { grades[l.grade] += 1; });
  return {
    activeListings: active.length, availableQuantityKg: active.reduce((s, l) => s + l.quantityKg, 0),
    pendingOrders: orders.filter((o) => ["created", "reserved", "payment_confirmed"].includes(o.status)).length,
    earnings: orders.filter((o) => o.paymentStatus === "success").reduce((s, o) => s + o.totalAmount, 0),
    gradingSummary: grades, sales: series([22, 28, 26, 35, 41, 48]), prices: series([21.5, 24, 22.5, 27, 29.5, 32]),
  };
}

function analytics(d: DemoDb): AdminAnalyticsDto {
  return {
    totalUsers: 1284, activeFarmers: 612, activeBuyers: 236, listings: 940 + d.listings.length, transactions: 3100 + d.orders.length,
    transactionValue: 18_450_000 + d.orders.filter((o) => o.paymentStatus === "success").reduce((s, o) => s + o.totalAmount, 0),
    flaggedActivities: d.risk.length + d.approvals.filter((a) => a.status === "pending").length, series: series([22, 28, 26, 35, 41, 48]),
  };
}

const VOICE: Record<string, { transcript: string; answer: string }> = {
  en: { transcript: "What is today's tomato price in Kolar?", answer: "Grade A tomatoes are trading around ₹31 to ₹34 per kg at Kolar today, slightly up from last week. Selling in the next two days should get you a good price." },
  hi: { transcript: "आज कोलार में टमाटर का भाव क्या है?", answer: "आज कोलार में ग्रेड A टमाटर ₹31 से ₹34 प्रति किलो बिक रहे हैं, पिछले हफ़्ते से थोड़ा ऊपर। अगले दो दिनों में बेचने पर अच्छा दाम मिलेगा।" },
  kn: { transcript: "ಇಂದು ಕೋಲಾರದಲ್ಲಿ ಟೊಮೆಟೊ ಬೆಲೆ ಎಷ್ಟು?", answer: "ಇಂದು ಕೋಲಾರದಲ್ಲಿ ಗ್ರೇಡ್ A ಟೊಮೆಟೊ ಕಿಲೋಗೆ ₹31 ರಿಂದ ₹34 ರಷ್ಟಿದೆ, ಕಳೆದ ವಾರಕ್ಕಿಂತ ಸ್ವಲ್ಪ ಹೆಚ್ಚು. ಮುಂದಿನ ಎರಡು ದಿನಗಳಲ್ಲಿ ಮಾರಿದರೆ ಒಳ್ಳೆಯ ಬೆಲೆ ಸಿಗುತ್ತದೆ." },
};

/** Grading takes a realistic ~3.5 s: queued → analyzing → ready. */
function gradingJob(d: DemoDb, id: string): GradingJobDto {
  const job = d.jobs.get(id);
  if (!job) throw notFound("Grading job");
  const age = Date.now() - job.startedMs;
  if (age < 1200) return { jobId: id, status: "queued", progress: 5 };
  if (age < 3300) return { jobId: id, status: "analyzing", progress: 50 };
  return { jobId: id, status: "ready", progress: 100, result: { jobId: id, gradedAt: new Date(job.startedMs + 3300).toISOString(), ...gradeFor(job.cropName) } };
}

/* ---------------- router ---------------- */
export async function handleDemoRequest(method: string, rawPath: string, query: Query = {}, body: unknown = {}): Promise<unknown> {
  const d = getDb();
  const m = method.toUpperCase();
  const path = (rawPath.split("?")[0] ?? "").replace(/\/+$/, "") || "/";
  const seg = path.split("/").filter(Boolean);
  const b: Body = body && typeof body === "object" && !(typeof FormData !== "undefined" && body instanceof FormData) ? (body as Body) : {};
  const is = (verb: string, p: string) => m === verb && path === p;

  /* auth */
  if (is("POST", "/auth/demo")) {
    const role = str(b.role) as Role;
    if (!DEMO_USERS[role]) throw new ApiError(400, "Unknown demo role");
    writeRole(role);
    return { user: DEMO_USERS[role] };
  }
  if (is("POST", "/auth/login")) {
    const email = str(b.email).toLowerCase();
    const role: Role = email.includes("admin") ? "admin" : email.includes("farmer") ? "farmer" : "buyer";
    writeRole(role);
    return { user: DEMO_USERS[role] };
  }
  if (is("POST", "/auth/otp/request")) return { sent: true };
  if (is("POST", "/auth/otp/verify")) {
    if (!/^\d{6}$/.test(str(b.code))) throw new ApiError(400, "Enter the 6-digit code");
    writeRole("farmer");
    return { user: DEMO_USERS.farmer };
  }
  if (is("POST", "/auth/google")) { writeRole("buyer"); return { user: DEMO_USERS.buyer }; }
  if (is("POST", "/auth/logout")) { writeRole(null); return undefined; }
  if (is("GET", "/auth/me")) return user();

  /* public marketplace read */
  if (is("GET", "/listings")) {
    user();
    const f: ListingFilters = { q: q(query, "q"), crop: q(query, "crop"), grade: q(query, "grade") as ListingFilters["grade"], location: q(query, "location"), sort: q(query, "sort") as ListingFilters["sort"] };
    const minP = q(query, "minPrice"), maxP = q(query, "maxPrice"), minQ = q(query, "minQuantity");
    let items = d.listings.filter((l) => l.status === "active");
    if (f.q) items = items.filter((l) => [l.crop, l.farmerName, l.location].some((x) => x.toLowerCase().includes(f.q!.toLowerCase())));
    if (f.crop) items = items.filter((l) => l.crop.toLowerCase().includes(f.crop!.toLowerCase()));
    if (f.grade) items = items.filter((l) => l.grade === f.grade);
    if (f.location) items = items.filter((l) => l.location.toLowerCase().includes(f.location!.toLowerCase()));
    if (minP) items = items.filter((l) => l.pricePerKg >= Number(minP));
    if (maxP) items = items.filter((l) => l.pricePerKg <= Number(maxP));
    if (minQ) items = items.filter((l) => l.quantityKg >= Number(minQ));
    const sorters: Record<string, (a: ListingDto, c: ListingDto) => number> = {
      price_asc: (a, c) => a.pricePerKg - c.pricePerKg, price_desc: (a, c) => c.pricePerKg - a.pricePerKg, quantity_desc: (a, c) => c.quantityKg - a.quantityKg,
      newest: (a, c) => c.createdAt.localeCompare(a.createdAt),
    };
    items = [...items].sort(sorters[f.sort ?? "newest"] ?? sorters.newest!);
    const page = Math.max(1, num(q(query, "page"), 1));
    const pageSize = 12;
    return { items: items.slice((page - 1) * pageSize, page * pageSize), total: items.length, page, pageSize };
  }
  if (m === "GET" && seg[0] === "listings" && seg[1]) { user(); const l = d.listings.find((x) => x.id === seg[1]); if (!l) throw notFound("Listing"); return l; }

  const u = user(); // everything below needs a session

  /* farmer */
  if (is("GET", "/farmer/listings")) { need(u, "farmer"); return d.listings.filter((l) => l.farmerName === u.name); }
  if (is("GET", "/farmer/dashboard")) { need(u, "farmer"); return farmerDashboard(u, d); }
  if (is("POST", "/listings")) {
    need(u, "farmer");
    const job = d.jobs.get(str(b.gradingJobId));
    const crop = str(b.crop, "Tomato");
    const res = gradeFor(job?.cropName ?? crop);
    const id = `l${++d.seq}`;
    const l: ListingDto = {
      id, crop: crop[0]!.toUpperCase() + crop.slice(1), grade: res.grade, quantityKg: num(b.quantityKg), pricePerKg: num(b.pricePerKg), location: str(b.location),
      farmerName: u.name, farmerVerified: true, images: [cropImage(str((b.imageKeys as string[] | undefined)?.[0]).replace("samples/", "") || crop)],
      status: res.manualReviewRecommended ? "pending_review" : "active", availableFrom: dateOnly(0), createdAt: isoAt(0),
    };
    d.listings.unshift(l);
    if (l.status === "pending_review") {
      d.approvals.unshift({ id: `a${++d.seq}`, listingId: id, title: `Publish listing: ${l.crop}, ${l.quantityKg.toLocaleString("en-IN")} kg`, reason: `Low AI confidence (${Math.round(res.confidence * 100)}%). Manual review required before publishing.`, status: "pending", history: [{ at: isoAt(0), actor: "System", action: "flagged for approval" }] });
    }
    addNotification(d, l.status === "active" ? `Your ${l.crop} listing is live` : `Your ${l.crop} listing is waiting for admin approval`);
    return l;
  }
  if (m === "DELETE" && seg[0] === "listings" && seg[1]) {
    need(u, "farmer");
    const i = d.listings.findIndex((x) => x.id === seg[1] && x.farmerName === u.name);
    if (i < 0) throw notFound("Listing");
    d.listings.splice(i, 1);
    return undefined;
  }

  /* uploads (no real S3 in demo) */
  if (is("POST", "/uploads/init")) return { uploadUrl: "demo://upload", objectKey: `uploads/${Date.now()}-${str(b.fileName, "photo.jpg")}` };
  if (is("POST", "/uploads/confirm")) { const k = str(b.objectKey); return { id: `img-${k}`, objectKey: k, url: "/demo-crops/tomato.svg" } satisfies ImageDto; }
  if (is("POST", "/uploads/sample")) { const id = str(b.sampleId, "tomato"); return { id: `img-${id}`, objectKey: `samples/${id}`, url: `/demo-crops/${CROPS.find((c) => c === id) ?? "tomato"}.svg` } satisfies ImageDto; }

  /* grading + pricing */
  if (is("POST", "/grading")) {
    const key = str((b.imageKeys as string[] | undefined)?.[0]);
    const fromKey = CROPS.find((c) => key.includes(c));
    const id = `job${++d.seq}`;
    d.jobs.set(id, { startedMs: Date.now(), cropName: fromKey ?? str(b.cropName, "Tomato") });
    return { jobId: id };
  }
  if (is("GET", "/admin/grading")) {
    need(u, "admin");
    return CROPS.map((c, i) => ({ jobId: `hist-${i}`, status: "ready", progress: 100, result: { jobId: `hist-${i}`, gradedAt: isoAt(-(i + 1) * 3 * 3_600_000), ...gradeFor(c) } }) satisfies GradingJobDto);
  }
  if (m === "GET" && seg[0] === "grading" && seg[1]) return gradingJob(d, seg[1]);
  if (is("GET", "/pricing/suggest")) return priceFor(q(query, "crop") ?? "tomato", (q(query, "grade") as "A" | "B" | "C" | undefined) ?? "A");

  /* requirements + matching */
  if (is("GET", "/requirements")) { need(u, "buyer"); return d.requirements.map(({ createdMs: _c, ...r }) => r); }
  if (is("POST", "/requirements")) {
    need(u, "buyer");
    const r: DemoRequirement = {
      id: `r${++d.seq}`, crop: str(b.crop), quantityKg: num(b.quantityKg), desiredGrade: (str(b.desiredGrade, "A") as "A" | "B" | "C"), destination: str(b.destination),
      deliveryDate: str(b.deliveryDate), maxBudget: num(b.maxBudget), status: "matching", createdAt: isoAt(0), createdMs: Date.now(),
    };
    d.requirements.unshift(r);
    const { createdMs: _c, ...out } = r;
    return out;
  }
  if (is("GET", "/matches")) {
    need(u, "buyer");
    const id = q(query, "requirementId");
    const req = id ? d.requirements.find((r) => r.id === id) : d.requirements[0];
    if (!req) return [];
    if (Date.now() - req.createdMs < 1800 && req.id !== "r1") return []; // "Finding suitable farmers…"
    if (req.status === "matching") req.status = "matched";
    return d.listings.map((l) => matchListing(req, l)).filter((x): x is MatchDto => x !== null).sort((a, c) => c.score - a.score);
  }

  /* orders + payments */
  if (is("GET", "/orders")) return visibleOrders(u, d);
  if (m === "GET" && seg[0] === "orders" && seg[1] && !seg[2]) { const o = visibleOrders(u, d).find((x) => x.id === seg[1]); if (!o) throw notFound("Order"); return o; }
  if (is("POST", "/orders")) {
    need(u, "buyer");
    const l = d.listings.find((x) => x.id === str(b.listingId) && x.status === "active");
    if (!l) throw notFound("Listing");
    const qty = num(b.quantityKg);
    if (!(qty > 0) || qty > l.quantityKg) throw new ApiError(400, `Only ${l.quantityKg.toLocaleString("en-IN")} kg available`);
    const o = makeOrder(`o${++d.seq}`, l, qty, "reserved", "not_started", u.name, Date.now());
    d.orders.unshift(o);
    addNotification(d, `Order ${o.id} reserved. Complete payment to confirm.`);
    return o;
  }
  if (m === "POST" && seg[0] === "orders" && seg[1] && seg[2]) {
    const o = d.orders.find((x) => x.id === seg[1]);
    if (!o) throw notFound("Order");
    if (seg[2] === "confirm") {
      need(u, "farmer");
      if (o.status === "payment_confirmed") { o.status = "farmer_confirmed"; o.timeline.push({ step: "farmer_confirmed", at: isoAt(0) }); }
    } else if (seg[2] === "cancel") {
      o.status = "cancelled";
    }
    return o;
  }
  if (is("GET", "/payments")) return visibleOrders(u, d).map(paymentSession);
  if (is("POST", "/payments/initiate")) {
    need(u, "buyer");
    const o = d.orders.find((x) => x.id === str(b.orderId)); if (!o) throw notFound("Order");
    if (o.paymentStatus === "not_started" || o.paymentStatus === "failed") o.paymentStatus = "pending";
    return paymentSession(o);
  }
  if (is("POST", "/payments/confirm")) {
    need(u, "buyer");
    const o = d.orders.find((x) => x.id === str(b.orderId)); if (!o) throw notFound("Order");
    o.paymentStatus = "success";
    o.transactionId = o.transactionId ?? `TXN-${o.id.toUpperCase()}-${String(Date.now()).slice(-5)}`;
    if (o.status === "created" || o.status === "reserved") {
      o.status = "payment_confirmed";
      if (!o.timeline.some((t) => t.step === "reserved")) o.timeline.push({ step: "reserved", at: isoAt(-1000) });
      o.timeline.push({ step: "payment_confirmed", at: isoAt(0) });
    }
    addNotification(d, `Payment confirmed for order ${o.id}`);
    return paymentSession(o);
  }
  if (m === "GET" && seg[0] === "payments" && seg[1]) { const o = visibleOrders(u, d).find((x) => x.id === seg[1]); if (!o) throw notFound("Order"); return paymentSession(o); }

  /* notifications */
  if (is("GET", "/notifications")) return d.notifications;
  if (m === "POST" && seg[0] === "notifications" && seg[2] === "read") { const n = d.notifications.find((x) => x.id === seg[1]); if (n) n.read = true; return undefined; }

  /* voice */
  if (is("POST", "/voice/ask")) {
    const lang = body instanceof FormData ? String(body.get("language") ?? "en") : "en";
    return (VOICE[lang] ?? VOICE.en!) satisfies VoiceReplyDto;
  }

  /* admin */
  if (seg[0] === "admin") {
    need(u, "admin");
    if (is("GET", "/admin/analytics")) return analytics(d);
    if (is("GET", "/admin/users")) return [...Object.values(DEMO_USERS), { id: "u-4", name: "Lakshmi Devi", role: "farmer", phone: "+919845012345" }, { id: "u-5", name: "Suresh Patil", role: "farmer", phone: "+919822098765" }, { id: "u-6", name: "Green Mart", role: "buyer", email: "ops@greenmart.example" }] satisfies UserDto[];
    if (is("GET", "/admin/listings")) return d.listings;
    if (is("GET", "/admin/transactions")) return d.orders;
    if (is("GET", "/admin/risk")) return d.risk;
    if (is("GET", "/admin/audit-logs")) return d.audit;
    if (is("GET", "/admin/approvals")) return d.approvals.map(({ listingId: _l, ...a }) => a) satisfies ApprovalDto[];
    if (m === "POST" && seg[1] === "approvals" && seg[2]) {
      const a = d.approvals.find((x) => x.id === seg[2]) as DemoApproval | undefined;
      if (!a) throw notFound("Approval");
      const action = str(b.action);
      const map = { approve: ["approved", "approved"], reject: ["rejected", "rejected"], request_review: ["review_requested", "requested a review of"] } as const;
      const hit = map[action as keyof typeof map];
      if (!hit) throw new ApiError(400, "Unknown action");
      a.status = hit[0];
      a.history.push({ at: isoAt(0), actor: u.name, action: hit[1], note: str(b.note) || undefined });
      addAudit(d, u.name, `${hit[1][0]!.toUpperCase()}${hit[1].slice(1)}: ${a.title}`, a.listingId ? `Listing ${a.listingId}` : "Approval");
      const l = a.listingId ? d.listings.find((x) => x.id === a.listingId) : undefined;
      if (l && action === "approve") l.status = "active";
      if (l && action === "reject") l.status = "rejected";
      const { listingId: _l, ...out } = a;
      return out;
    }
  }

  throw new ApiError(404, `No demo handler for ${m} ${path}`);
}
