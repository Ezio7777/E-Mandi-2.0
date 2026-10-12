// QA-only mock of the E-Mandi backend contract. NOT part of the app bundle.
// Usage: node tools/mock-api/server.mjs   (listens on :8000, CORS for http://localhost:3000)
import http from "node:http";

const ORIGIN = process.env.ALLOW_ORIGIN ?? "http://localhost:3000";
const now = () => new Date().toISOString();
const img = (n) => ({ id: `img-${n}`, objectKey: `k/${n}`, url: `/demo-crops/${n}.svg` });
const L = (id, crop, grade, qty, price, loc, farmer, status = "active", n = crop.toLowerCase()) => ({
  id, crop, grade, quantityKg: qty, pricePerKg: price, location: loc, farmerName: farmer, farmerVerified: id !== "l3",
  images: [img(n)], status, createdAt: "2026-09-20T08:00:00Z", availableFrom: "2026-10-01",
});
const listings = [
  L("l1", "Tomato", "A", 800, 32, "Hosur, Tamil Nadu", "Ravi Kumar"),
  L("l2", "Potato", "B", 1200, 18, "Kolar, Karnataka", "Lakshmi Devi"),
  L("l3", "Onion", "A", 2500, 24, "Nashik, Maharashtra", "Suresh Patil", "pending_review"),
  L("l4", "Cabbage", "C", 400, 12, "Mysuru, Karnataka", "Anita Rao"),
];
const order = (id, status, pay) => ({
  id, transactionId: pay === "success" ? `TXN-${id}` : undefined, listing: listings[0], farmerName: "Ravi Kumar", buyerName: "Fresh Basket Pvt Ltd",
  quantityKg: 500, pricePerKg: 32, totalAmount: 16000, status, paymentStatus: pay, createdAt: "2026-09-28T09:30:00Z",
  timeline: ["created", "reserved", "payment_confirmed", "farmer_confirmed", "fulfilled", "completed"]
    .slice(0, { created: 1, reserved: 2, payment_confirmed: 3, farmer_confirmed: 4, fulfilled: 5, completed: 6 }[status]).map((step, i) => ({ step, at: `2026-09-28T0${9 + i}:30:00Z` })),
});
const orders = [order("o1", "payment_confirmed", "success"), order("o2", "reserved", "not_started"), order("o3", "completed", "success")];
const users = {
  farmer: { id: "u1", name: "Ravi Kumar", role: "farmer", phone: "+919876543210", location: "Hosur", isDemo: true },
  buyer: { id: "u2", name: "Fresh Basket Pvt Ltd", role: "buyer", email: "buyer@demo.emandi", isDemo: true },
  admin: { id: "u3", name: "Admin Demo", role: "admin", email: "admin@demo.emandi", isDemo: true },
};
const series = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"].map((label, i) => ({ label, value: [22, 28, 26, 35, 41, 48][i] }));
const jobs = new Map();

const roleOf = (req) => /mockrole=(\w+)/.exec(req.headers.cookie ?? "")?.[1];
const send = (res, code, body, extra = {}) => {
  res.writeHead(code, { "Content-Type": "application/json", "Access-Control-Allow-Origin": ORIGIN, "Access-Control-Allow-Credentials": "true", ...extra });
  res.end(body === undefined ? "" : JSON.stringify(body));
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname;
  if (req.method === "OPTIONS") return send(res, 204, undefined, { "Access-Control-Allow-Headers": "Content-Type, Authorization", "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE" });
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    const body = raw && req.headers["content-type"]?.includes("json") ? JSON.parse(raw) : {};
    const role = roleOf(req);
    if (process.env.MOCK_DELAY) return setTimeout(() => route(), Number(process.env.MOCK_DELAY));
    route();
    function route() {
      if (p === "/auth/demo") return send(res, 200, { user: users[body.role] }, { "Set-Cookie": `mockrole=${body.role}; Path=/` });
      if (p === "/auth/logout") return send(res, 204, undefined, { "Set-Cookie": "mockrole=; Path=/; Max-Age=0" });
      if (p === "/auth/me") return role ? send(res, 200, users[role]) : send(res, 401, { message: "Not signed in" });
      if (p === "/auth/login") return send(res, 200, { user: users.buyer }, { "Set-Cookie": "mockrole=buyer; Path=/" });
      if (!role && !p.startsWith("/listings")) return send(res, 401, { message: "Not signed in" });
      if (p === "/farmer/dashboard") return send(res, 200, { activeListings: 6, availableQuantityKg: 5400, pendingOrders: 3, earnings: 184500, gradingSummary: { A: 9, B: 4, C: 1 }, sales: series, prices: series.map((s) => ({ ...s, value: s.value / 1.5 })) });
      if (p === "/farmer/listings") return send(res, 200, listings);
      if (p === "/listings") return send(res, 200, { items: listings.filter((l) => l.status === "active" && (!url.searchParams.get("crop") || l.crop.toLowerCase().includes(url.searchParams.get("crop").toLowerCase()))), total: 3, page: 1, pageSize: 12 });
      if (p.startsWith("/listings/")) { const l = listings.find((x) => x.id === p.split("/")[2]); return l ? send(res, 200, l) : send(res, 404, { message: "Listing not found" }); }
      if (p === "/orders" && req.method === "GET") return send(res, 200, orders);
      if (p === "/orders") return send(res, 200, orders[1]);
      if (p.startsWith("/orders/")) { const o = orders.find((x) => x.id === p.split("/")[2]); return o ? send(res, 200, o) : send(res, 404, { message: "Order not found" }); }
      if (p === "/payments" && req.method === "GET") return send(res, 200, orders.map((o) => ({ orderId: o.id, provider: "razorpay-test", providerOrderId: `po_${o.id}`, amount: o.totalAmount, currency: "INR", status: o.paymentStatus })));
      if (p === "/payments/initiate" || p === "/payments/confirm") return send(res, 200, { orderId: body.orderId, provider: "razorpay-test", providerOrderId: "po_1", amount: 16000, currency: "INR", publicKey: "rzp_test_x", status: "success" });
      if (p.startsWith("/payments/")) return send(res, 200, { orderId: p.split("/")[2], provider: "razorpay-test", providerOrderId: "po_1", amount: 16000, currency: "INR", status: "not_started" });
      if (p === "/requirements" && req.method === "GET") return send(res, 200, [{ id: "r1", crop: "Tomato", quantityKg: 500, desiredGrade: "A", destination: "Bangalore", deliveryDate: "2026-10-02", maxBudget: 20000, status: "matched", createdAt: now() }]);
      if (p === "/requirements") return send(res, 200, { id: "r2", ...body, status: "matching", createdAt: now() });
      if (p === "/matches") return send(res, 200, [
        { listingId: "l1", score: 0.92, listing: listings[0], reasons: [{ factor: "grade", matched: true, detail: "Grade A as requested" }, { factor: "quantity", matched: true, detail: "800 kg available, you need 500 kg" }, { factor: "location", matched: true, detail: "About 40 km from Bangalore" }, { factor: "price", matched: true, detail: "₹32/kg is inside your budget" }, { factor: "availability", matched: false, detail: "Available from 1 Oct, you need it by 30 Sep" }] },
        { listingId: "l2", score: 0.61, listing: listings[1], reasons: [{ factor: "grade", matched: false, detail: "Grade B, you asked for A" }, { factor: "quantity", matched: true, detail: "1,200 kg available" }, { factor: "location", matched: true, detail: "About 70 km from Bangalore" }, { factor: "price", matched: true, detail: "₹18/kg is inside your budget" }, { factor: "availability", matched: true, detail: "Available now" }] },
      ]);
      if (p === "/uploads/init") return send(res, 200, { uploadUrl: "http://localhost:8000/__s3", objectKey: `uploads/${Date.now()}.jpg` });
      if (p === "/__s3") return send(res, 200, {});
      if (p === "/uploads/confirm") return send(res, 200, { id: "i", objectKey: body.objectKey, url: "/demo-crops/tomato.svg" });
      if (p === "/uploads/sample") return send(res, 200, { id: "s", objectKey: `samples/${body.sampleId}`, url: `/demo-crops/${body.sampleId}.svg` });
      if (p === "/grading" && req.method === "POST") { const id = `j${jobs.size + 1}`; jobs.set(id, Date.now()); return send(res, 200, { jobId: id }); }
      if (p === "/admin/grading") return send(res, 200, [{ jobId: "j9", status: "ready", result: { jobId: "j9", grade: "B", confidence: 0.58, defectPercent: 11, explanation: "x", issues: [], gradedAt: now(), manualReviewRecommended: true } }, { jobId: "j8", status: "ready", result: { jobId: "j8", grade: "A", confidence: 0.94, defectPercent: 2.5, explanation: "x", issues: [], gradedAt: now(), manualReviewRecommended: false } }]);
      if (p.startsWith("/grading/")) {
        const t = jobs.get(p.split("/")[2]) ?? 0; const age = Date.now() - t;
        if (age < 1500) return send(res, 200, { jobId: p.split("/")[2], status: "queued" });
        if (age < 3500) return send(res, 200, { jobId: p.split("/")[2], status: "analyzing", progress: 50 });
        return send(res, 200, { jobId: p.split("/")[2], status: "ready", result: { jobId: p.split("/")[2], grade: "A", confidence: 0.94, defectPercent: 2.5, explanation: "Minor surface bruising detected on a few fruits. Colour and firmness are consistent across the lot.", issues: ["Surface bruising", "Slight colour variation"], provider: "Gemini Vision", gradedAt: now(), manualReviewRecommended: false } });
      }
      if (p === "/pricing/suggest") return send(res, 200, { suggested: 32, rangeMin: 29, rangeMax: 35, referencePrice: 31, trend: "up", explanation: "Arrivals at Kolar APMC are lower than last week, supporting a slightly higher price for Grade A.", source: "Agmarknet, Kolar APMC" });
      if (p === "/listings" && req.method === "POST") return send(res, 200, listings[0]);
      if (p === "/voice/ask") return send(res, 200, { transcript: "What is today's tomato price in Kolar?", answer: "Grade A tomatoes are trading around ₹31 to ₹34 per kg at Kolar today, slightly up from last week." });
      if (p === "/notifications") return send(res, 200, [{ id: "n1", title: "Payment confirmed for order o1", read: false, at: now() }, { id: "n2", title: "Your Tomato listing is live", read: true, at: now() }]);
      if (p.startsWith("/notifications/")) return send(res, 204);
      if (p === "/admin/analytics") return send(res, 200, { totalUsers: 1284, activeFarmers: 612, activeBuyers: 236, listings: 948, transactions: 3120, transactionValue: 18450000, flaggedActivities: 7, series });
      if (p === "/admin/users") return send(res, 200, Object.values(users));
      if (p === "/admin/listings") return send(res, 200, listings);
      if (p === "/admin/transactions") return send(res, 200, orders);
      if (p === "/admin/risk") return send(res, 200, [
        { id: "f1", severity: "high", event: "Unusually low bid on 2,500 kg Onion", entity: "Bid #4821 by Buyer B-118", reason: "Bid is 46% below the 30-day reference price for this grade.", recommendedAction: "Review the bid before accepting.", at: now() },
        { id: "f2", severity: "medium", event: "Repeated failed payments", entity: "Buyer B-204", reason: "4 failed payment attempts in 20 minutes.", recommendedAction: "Contact the buyer; consider a temporary hold.", at: now() },
        { id: "f3", severity: "low", event: "Low AI grading confidence", entity: "Listing l3", reason: "Grading confidence 58%, below the review threshold.", recommendedAction: "Request manual grading review.", at: now() },
      ]);
      if (p === "/admin/approvals" && req.method === "GET") return send(res, 200, [
        { id: "a1", title: "Publish listing: Onion, 2,500 kg", reason: "Low AI confidence (58%). Manual review required before publishing.", status: "pending", history: [{ at: now(), actor: "System", action: "flagged for approval" }] },
        { id: "a2", title: "Refund order o7", reason: "Buyer dispute: quantity mismatch.", status: "approved", history: [{ at: now(), actor: "Admin Demo", action: "approved", note: "Verified with farmer" }] },
      ]);
      if (p.startsWith("/admin/approvals/")) return send(res, 200, { id: "a1", title: "x", reason: "x", status: "approved", history: [] });
      if (p === "/admin/audit-logs") return send(res, 200, [{ id: "au1", at: now(), actor: "Admin Demo", action: "Approved refund", entity: "Order o7" }, { id: "au2", at: now(), actor: "System", action: "Flagged listing", entity: "Listing l3" }]);
      send(res, 404, { message: `No mock for ${req.method} ${p}` });
    }
  });
});
server.listen(8000, () => console.log("mock api on :8000"));
