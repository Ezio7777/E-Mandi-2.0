import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { ApprovalDto, GradingJobDto, ListingDto, MatchDto, OrderDto, PaymentSessionDto } from "@/types";
import { handleDemoRequest as call, resetDemoDb } from "./handler";

const as = (role: "farmer" | "buyer" | "admin") => call("POST", "/auth/demo", {}, { role });
const get = <T>(path: string, query = {}) => call("GET", path, query) as Promise<T>;
const post = <T>(path: string, body = {}) => call("POST", path, {}, body) as Promise<T>;
const status = async (p: Promise<unknown>) => { try { await p; return 200; } catch (e) { return e instanceof ApiError ? e.status : -1; } };

beforeEach(() => { window.localStorage.clear(); resetDemoDb(); vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(new Date("2026-10-10T10:00:00Z")); });
afterEach(() => vi.useRealTimers());

describe("demo API: sessions and roles", () => {
  it("rejects unauthenticated calls with 401", async () => {
    expect(await status(get("/auth/me"))).toBe(401);
    expect(await status(get("/orders"))).toBe(401);
  });
  it("logs in as each demo role and persists the session until logout", async () => {
    await as("farmer");
    expect(await get<{ role: string; isDemo: boolean }>("/auth/me")).toMatchObject({ role: "farmer", isDemo: true });
    await post("/auth/logout");
    expect(await status(get("/auth/me"))).toBe(401);
  });
  it("enforces role boundaries like the real backend", async () => {
    await as("farmer");
    expect(await status(get("/admin/analytics"))).toBe(403);
    expect(await status(get("/requirements"))).toBe(403);
    await as("buyer");
    expect(await status(post("/listings", { crop: "Tomato" }))).toBe(403);
    await as("admin");
    expect(await status(get("/farmer/dashboard"))).toBe(403);
  });
  it("validates the phone OTP code format", async () => {
    expect(await status(post("/auth/otp/verify", { phone: "9876543210", code: "12" }))).toBe(400);
    expect(await status(post("/auth/otp/verify", { phone: "9876543210", code: "123456" }))).toBe(200);
  });
});

describe("demo API: marketplace", () => {
  it("hides listings awaiting review and filters/sorts", async () => {
    await as("buyer");
    const all = await get<{ items: ListingDto[]; total: number }>("/listings");
    expect(all.items.every((l) => l.status === "active")).toBe(true);
    expect(all.items.find((l) => l.id === "l3")).toBeUndefined();
    const tomatoes = await get<{ items: ListingDto[] }>("/listings", { crop: "tomato", sort: "price_asc" });
    expect(tomatoes.items.length).toBeGreaterThan(1);
    expect(tomatoes.items.every((l) => l.crop === "Tomato")).toBe(true);
    expect(tomatoes.items.map((l) => l.pricePerKg)).toEqual([...tomatoes.items.map((l) => l.pricePerKg)].sort((a, b) => a - b));
  });
  it("returns 404 for a missing listing and for unknown routes", async () => {
    await as("buyer");
    expect(await status(get("/listings/nope"))).toBe(404);
    expect(await status(get("/does/not/exist"))).toBe(404);
  });
});

describe("demo API: AI grading and listing creation", () => {
  const grade = async (sample: string) => {
    const { jobId } = await post<{ jobId: string }>("/grading", { imageKeys: [`samples/${sample}`], cropName: sample });
    return jobId;
  };
  it("takes time: queued → analyzing → ready", async () => {
    await as("farmer");
    const id = await grade("tomato");
    expect((await get<GradingJobDto>(`/grading/${id}`)).status).toBe("queued");
    vi.setSystemTime(Date.now() + 2000);
    expect((await get<GradingJobDto>(`/grading/${id}`)).status).toBe("analyzing");
    vi.setSystemTime(Date.now() + 2500);
    const done = await get<GradingJobDto>(`/grading/${id}`);
    expect(done.status).toBe("ready");
    expect(done.result).toMatchObject({ grade: "A", manualReviewRecommended: false });
    expect(done.result!.confidence).toBeGreaterThan(0.9);
  });
  it("gives the cabbage sample a low-confidence 'manual review' result", async () => {
    await as("farmer");
    const id = await grade("cabbage");
    vi.setSystemTime(Date.now() + 5000);
    expect((await get<GradingJobDto>(`/grading/${id}`)).result).toMatchObject({ grade: "C", manualReviewRecommended: true });
  });
  it("suggests a price that depends on crop and grade", async () => {
    await as("farmer");
    const a = await get<{ suggested: number }>("/pricing/suggest", { crop: "Tomato", grade: "A" });
    const c = await get<{ suggested: number }>("/pricing/suggest", { crop: "Tomato", grade: "C" });
    expect(a.suggested).toBe(32);
    expect(c.suggested).toBeLessThan(a.suggested);
  });
  it("publishes a good lot immediately, and routes a low-confidence lot through admin approval", async () => {
    await as("farmer");
    const good = await post<ListingDto>("/listings", { crop: "Tomato", quantityKg: 500, location: "Hosur", pricePerKg: 32, imageKeys: ["samples/tomato"], gradingJobId: await grade("tomato") });
    expect(good.status).toBe("active");
    const risky = await post<ListingDto>("/listings", { crop: "Cabbage", quantityKg: 300, location: "Mysuru", pricePerKg: 11, imageKeys: ["samples/cabbage"], gradingJobId: await grade("cabbage") });
    expect(risky.status).toBe("pending_review");
    expect((await get<ListingDto[]>("/farmer/listings")).map((l) => l.id)).toEqual(expect.arrayContaining([good.id, risky.id]));

    await as("admin");
    const pending = (await get<ApprovalDto[]>("/admin/approvals")).find((a) => a.title.includes("Cabbage"))!;
    expect(pending.status).toBe("pending");
    const decided = await post<ApprovalDto>(`/admin/approvals/${pending.id}`, { action: "approve", note: "Looks fine" });
    expect(decided.status).toBe("approved");
    expect(decided.history.at(-1)).toMatchObject({ actor: "Admin Demo", note: "Looks fine" });
    const log = await get<{ action: string }[]>("/admin/audit-logs");
    expect(log[0]!.action).toMatch(/Approved/);
    await as("buyer");
    expect((await get<{ items: ListingDto[] }>("/listings", { crop: "cabbage" })).items.some((l) => l.id === risky.id)).toBe(true);
  });
});

describe("demo API: orders, payments, matching", () => {
  it("runs the buyer order → pay → farmer confirm lifecycle", async () => {
    await as("buyer");
    const order = await post<OrderDto>("/orders", { listingId: "l1", quantityKg: 100 });
    expect(order).toMatchObject({ status: "reserved", paymentStatus: "not_started", totalAmount: 3200 });
    expect(await status(post("/orders", { listingId: "l1", quantityKg: 999999 }))).toBe(400);

    expect((await post<PaymentSessionDto>("/payments/initiate", { orderId: order.id })).status).toBe("pending");
    const paid = await post<PaymentSessionDto>("/payments/confirm", { orderId: order.id });
    expect(paid.status).toBe("success");
    const after = await get<OrderDto>(`/orders/${order.id}`);
    expect(after.status).toBe("payment_confirmed");
    expect(after.transactionId).toMatch(/^TXN-/);
    expect(after.timeline.map((t) => t.step)).toEqual(["created", "reserved", "payment_confirmed"]);

    await as("farmer");
    expect((await post<OrderDto>(`/orders/${order.id}/confirm`)).status).toBe("farmer_confirmed");
  });
  it("shows each role only its own orders", async () => {
    await as("buyer");
    const mine = await get<OrderDto[]>("/orders");
    expect(mine.every((o) => o.buyerName === "Fresh Basket Pvt Ltd")).toBe(true);
    await as("farmer");
    expect((await get<OrderDto[]>("/orders")).every((o) => o.farmerName === "Ravi Kumar")).toBe(true);
  });
  it("matches a new requirement after a short 'finding farmers' delay, with all five reasons", async () => {
    await as("buyer");
    const r = await post<{ id: string }>("/requirements", { crop: "Tomato", quantityKg: 500, desiredGrade: "A", destination: "Bangalore", deliveryDate: "2026-10-11", maxBudget: 20000 });
    expect(await get<MatchDto[]>("/matches", { requirementId: r.id })).toEqual([]);
    vi.setSystemTime(Date.now() + 2500);
    const matches = await get<MatchDto[]>("/matches", { requirementId: r.id });
    expect(matches.length).toBeGreaterThan(0);
    expect(matches[0]!.reasons.map((x) => x.factor)).toEqual(["grade", "quantity", "location", "price", "availability"]);
    expect(matches[0]!.score).toBeGreaterThanOrEqual(matches.at(-1)!.score);
    expect(matches[0]!.listing.crop).toBe("Tomato");
  });
});
