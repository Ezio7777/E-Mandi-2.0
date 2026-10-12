import puppeteer from "puppeteer-core";
const B="http://localhost:3000";
const b = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", args: ["--no-sandbox","--disable-gpu"], headless: "new" });
const shots = [
  { n: "landing-390-light", path: "/", w: 390, h: 1500, theme: "light" },
  { n: "landing-1280-dark", path: "/", w: 1280, h: 900, theme: "dark" },
  { n: "farmer-dash-390-light", path: "/farmer/dashboard", role: "farmer", w: 390, h: 1400, theme: "light" },
  { n: "farmer-dash-1280-dark", path: "/farmer/dashboard", role: "farmer", w: 1280, h: 900, theme: "dark" },
  { n: "drawer-390", path: "/farmer/dashboard", role: "farmer", w: 390, h: 800, theme: "light", click: 'button[aria-label="Open menu"]' },
  { n: "market-390-dark", path: "/buyer/marketplace", role: "buyer", w: 390, h: 1500, theme: "dark" },
  { n: "matches-390-light", path: "/buyer/matches", role: "buyer", w: 390, h: 1500, theme: "light" },
  { n: "admin-analytics-320", path: "/admin/analytics", role: "admin", w: 320, h: 1300, theme: "light" },
  { n: "order-390-light", path: "/buyer/orders/o2", role: "buyer", w: 390, h: 1500, theme: "light" },
];
for (const s of shots) {
  const p = await b.newPage();
  await p.setViewport({ width: s.w, height: s.h, isMobile: s.w < 500, hasTouch: s.w < 500 });
  await p.evaluateOnNewDocument((t) => localStorage.setItem("emandi-theme", t), s.theme);
  if (s.role) await p.setCookie({ name: "mockrole", value: s.role, url: B }, { name: "emandi_session", value: "1", url: B });
  try {
  await p.goto(B + s.path, { waitUntil: "networkidle0", timeout: 30000 });
  if (s.click) { await p.click(s.click); await new Promise(r => setTimeout(r, 600)); }
  await new Promise(r => setTimeout(r, 600));
  await p.screenshot({ path: `shots/${s.n}.png` });
  } catch (e) { console.log('SHOT FAIL', s.n, e.message.slice(0,100)); try { await p.screenshot({ path: `shots/${s.n}-FAIL.png` }); } catch {} }
  await p.close();
}
await b.close();
