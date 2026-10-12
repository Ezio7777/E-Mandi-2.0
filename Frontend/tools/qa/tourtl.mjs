import puppeteer from "puppeteer-core";
const B = "http://localhost:3000";
const role = process.env.ROLE ?? "farmer";
const b = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", args: ["--no-sandbox", "--disable-gpu"], headless: "new" });
const p = await b.newPage();
await p.setViewport({ width: +(process.env.W ?? 1280), height: +(process.env.H ?? 800), isMobile: +(process.env.W ?? 1280) < 500, hasTouch: +(process.env.W ?? 1280) < 500 });
await p.evaluateOnNewDocument(() => {
  localStorage.setItem("emandi-theme", "dark");
  window.__log = []; let last = performance.now();
  const rect = (el) => { if (!el) return null; const r = el.getBoundingClientRect(); return { t: r.top, l: r.left, w: r.width, h: r.height }; };
  const tick = (now) => {
    const spot = document.querySelector("[data-tour-spotlight]"); const inner = document.querySelector("[data-tour-card-inner]");
    const card = document.querySelector("[data-tour-card]"); const layer = spot?.parentElement;
    window.__log.push({ now, dt: now - last, path: location.pathname, shell: !!document.querySelector("[data-shell-ready]"),
      spot: rect(spot), layer: layer ? +getComputedStyle(layer).opacity : 0, cardOp: inner ? +getComputedStyle(inner).opacity : 0, card: rect(card),
      title: document.querySelector("#tour-title")?.textContent ?? null });
    last = now; requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
});
await p.goto(B + "/login", { waitUntil: "networkidle0" });
await p.evaluate(() => (window.__log.length = 0));
await p.locator(`::-p-text(Try demo ${role})`).click();
await p.waitForFunction(() => location.pathname.startsWith("/" + "${role}".replace("${role}", "")) || true);
await new Promise((r) => setTimeout(r, 3200));
const marks = [];
const clicks = +(process.env.STEPS ?? 3);
for (let i = 0; i < clicks; i++) {
  marks.push(await p.evaluate(() => performance.now()));
  try { await p.locator('[role="dialog"] button ::-p-text(Next)').setTimeout(6000).click(); } catch (e) { console.log(`!! step ${i + 1}: Next not clickable (${e.message.slice(0, 60)})`); marks.pop(); break; }
  await new Promise((r) => setTimeout(r, 3600));
}
const log = await p.evaluate(() => window.__log);
await p.screenshot({ path: "shots/tour-last.png" });
await b.close();

const vis = (f) => f.cardOp > 0.05;
const out = [];
// A1: never a visible card/layer over login or before the shell exists
const overLogin = log.filter((f) => f.path.startsWith("/login") && (vis(f) || f.layer > 0.05));
const beforeShell = log.filter((f) => !f.shell && (vis(f) || f.layer > 0.05));
out.push(`A1 tour visible over login page: ${overLogin.length} frames (want 0)`);
out.push(`A2 tour visible before app shell exists: ${beforeShell.length} frames (want 0)`);
// A3: card never visible while spotlight is moving
let moving = 0, movingFrames = [];
for (let i = 1; i < log.length; i++) {
  const a = log[i - 1].spot, c = log[i].spot; if (!a || !c) continue;
  const d = Math.abs(a.t - c.t) + Math.abs(a.l - c.l) + Math.abs(a.w - c.w) + Math.abs(a.h - c.h);
  if (d > 3 && log[i].cardOp > 0.2) { moving++; movingFrames.push(`${log[i].title?.slice(0,18)} d=${d.toFixed(1)} op=${log[i].cardOp.toFixed(2)}`); }
}
out.push(`A3 frames where card is clearly visible while spotlight moves: ${moving} (want 0) ${movingFrames.slice(0,3).join(" | ")}`);
// A4: card does not jump while visible
let jumps = 0;
for (let i = 1; i < log.length; i++) { if (vis(log[i]) && vis(log[i - 1]) && log[i].card && log[i - 1].card) { const d = Math.abs(log[i].card.t - log[i - 1].card.t) + Math.abs(log[i].card.l - log[i - 1].card.l); if (d > 40) jumps++; } }
out.push(`A4 card position jumps while visible (>40px/frame): ${jumps} (want 0)`);
let flicker = 0;
for (let i = 1; i < log.length - 1; i++) { const a = log[i - 1].cardOp, b2 = log[i].cardOp, c = log[i + 1].cardOp; if ((a < 0.1 && b2 > 0.9 && c < 0.1) || (a > 0.9 && b2 < 0.1 && c > 0.9)) flicker++; }
out.push(`A5 single-frame card flickers: ${flicker} (want 0)`);
// per-step ordering + overlap
const stepsSeen = [];
for (const f of log) { if (f.title && vis(f) && stepsSeen[stepsSeen.length - 1]?.title !== f.title) stepsSeen.push({ ...f }); }
for (const s of stepsSeen) {
  let ov = 0;
  if (s.spot && s.card) { const ox = Math.max(0, Math.min(s.spot.l + s.spot.w, s.card.l + s.card.w) - Math.max(s.spot.l, s.card.l)); const oy = Math.max(0, Math.min(s.spot.t + s.spot.h, s.card.t + s.card.h) - Math.max(s.spot.t, s.card.t)); ov = ox * oy; }
  const area = s.spot ? s.spot.w * s.spot.h : 1;
  out.push(`step "${s.title}" on ${s.path}: card/spotlight overlap = ${(100 * ov / Math.max(area, 1)).toFixed(0)}% of highlight`);
}
// timing: from Next click to card visible again
for (const m of marks) {
  const after = log.filter((f) => f.now >= m);
  const hid = after.find((f) => f.cardOp < 0.05); const mv = after.find((f, i) => { const a = after[i - 1]?.spot, c = f.spot; return a && c && Math.abs(a.t - c.t) + Math.abs(a.l - c.l) + Math.abs(a.w - c.w) > 3; });
  const back = hid && after.find((f) => f.now > hid.now && f.cardOp > 0.9);
  out.push(`transition: card hidden +${hid ? (hid.now - m).toFixed(0) : "?"}ms, spotlight starts +${mv ? (mv.now - m).toFixed(0) : "n/a"}ms, card back +${back ? (back.now - m).toFixed(0) : "?"}ms`);
}
if (process.env.DUMP) { const m0 = marks[+process.env.DUMP]; let lastKey=""; for (const f of log) { if (f.now < m0 - 20 || f.now > m0 + 2600) continue; const key=[f.path, f.cardOp.toFixed(1), f.spot ? Math.round(f.spot.w/40) : "-", f.layer.toFixed(1)].join("|"); if (key===lastKey) continue; lastKey=key; out.push(`  +${(f.now-m0).toFixed(0).padStart(5)}ms ${f.path.padEnd(18)} card=${f.cardOp.toFixed(2)} layer=${f.layer.toFixed(2)} spot=${f.spot?`${f.spot.l.toFixed(0)},${f.spot.t.toFixed(0)} ${f.spot.w.toFixed(0)}x${f.spot.h.toFixed(0)}`:"-"} title="${(f.title??"").slice(0,22)}"`);} }
const dts = log.map((f) => f.dt).filter((d) => d < 1000).sort((a, b) => a - b);
out.push(`frame pacing: median ${dts[Math.floor(dts.length / 2)]?.toFixed(1)}ms, p95 ${dts[Math.floor(dts.length * 0.95)]?.toFixed(1)}ms, worst ${dts[dts.length - 1]?.toFixed(0)}ms (headless software render; relative only)`);
console.log(out.join("\n"));
