import puppeteer from "puppeteer-core";
import fs from "node:fs";
const CHROME = process.env.CHROME ?? "/usr/bin/google-chrome";
const BASE = "http://localhost:3000";
const routes = {
  public: ["/", "/how-it-works", "/login", "/demo", "/register"],
  farmer: ["/farmer/dashboard", "/farmer/sell", "/farmer/listings", "/farmer/listings/l1", "/farmer/orders", "/farmer/orders/o1", "/farmer/payments", "/farmer/assistant", "/farmer/profile"],
  buyer: ["/buyer/marketplace", "/buyer/marketplace/l1", "/buyer/requirements", "/buyer/requirements/new", "/buyer/matches", "/buyer/orders", "/buyer/orders/o2", "/buyer/checkout/o2", "/buyer/payments", "/buyer/profile"],
  admin: ["/admin/analytics", "/admin/users", "/admin/listings", "/admin/transactions", "/admin/grading", "/admin/risk", "/admin/approvals", "/admin/disputes", "/admin/audit-logs"],
};
const widths = (process.env.WIDTHS ?? "320,390,768,1280").split(",").map(Number);
const themes = (process.env.THEMES ?? "light,dark").split(",");
const only = process.env.ONLY;
const roleOnly = process.env.ROLE;
const browser = await puppeteer.launch({ executablePath: CHROME, args: ["--no-sandbox", "--disable-gpu"], headless: "new" });
const report = [];
const jobs = [];
for (const [role, list] of Object.entries(routes)) {
  if (roleOnly && role !== roleOnly) continue;
  for (const path of list) {
    if (only && !path.includes(only)) continue;
    for (const theme of themes) for (const w of widths) jobs.push({ role, path, theme, w });
  }
}
async function run(job) { try { await run0(job); } catch (e) { report.push({ path: job.path, w: job.w, theme: job.theme, fatal: 'harness: ' + e.message.slice(0, 100) }); } }
async function run0({ role, path, theme, w }) {
    {
      const page = await browser.newPage();
      await page.setViewport({ width: w, height: w < 500 ? 800 : 900, deviceScaleFactor: 1, isMobile: w < 500, hasTouch: w < 500 });
      await page.evaluateOnNewDocument((t, loc) => { localStorage.setItem("emandi-theme", t); if (loc) localStorage.setItem("emandi-client-state", JSON.stringify({ theme: { preference: "system", locale: loc } })); }, theme, process.env.LOCALE ?? "");
      if (role !== "public") {
        await page.setCookie({ name: "mockrole", value: role, url: BASE }, { name: "emandi_session", value: "1", url: BASE });
      }
      const errs = [];
      page.on("pageerror", (e) => errs.push("pageerror: " + e.message));
      page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errs.push("console: " + m.text().slice(0, 160)));
      page.on("response", (r) => r.status() >= 400 && r.url().includes(":8000") && errs.push(`${r.status()} ${r.url().replace("http://localhost:8000", "")}`));
      try {
        const resp = await page.goto(BASE + path, { waitUntil: "networkidle0", timeout: 45000 });
        if (!resp || resp.status() >= 400) errs.push("DOC STATUS " + (resp && resp.status()));
        await new Promise((r) => setTimeout(r, 700));
        const m = await page.evaluate(() => {
          const vw = document.documentElement.clientWidth;
          const offenders = [];
          document.querySelectorAll("body *").forEach((el) => {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.right > vw + 1 && !el.closest(".scroll-x, [data-allow-overflow], .overflow-x-auto")) {
              const cs = getComputedStyle(el);
              if (cs.position !== "fixed") offenders.push(`${el.tagName.toLowerCase()}.${(el.className?.toString() ?? "").split(" ").slice(0, 3).join(".")} r=${Math.round(r.right)}`);
            }
          });
          return { sw: document.documentElement.scrollWidth, vw, offenders: offenders.slice(0, 4), h1: document.querySelector("h1")?.textContent?.slice(0, 40) };
        });
        const overflow = m.sw > m.vw + 1;
        if (!m.h1) errs.push("NO H1 (blank/error page?)");
        const key = `${path.replace(/\//g, "_") || "_root"}__${w}__${theme}`;
        if (process.env.SHOTS !== "0" && (theme === "light" || process.env.ALLSHOTS)) await page.screenshot({ path: `shots/${key}.png`, fullPage: false });
        report.push({ path, w, theme, overflow, sw: m.sw, vw: m.vw, offenders: overflow ? m.offenders : [], h1: m.h1, errs });
      } catch (e) {
        report.push({ path, w, theme, fatal: e.message.slice(0, 120) });
      }
      try { await page.close(); } catch {}
    }
}
const queue = [...jobs];
await Promise.all(Array.from({ length: 2 }, async () => { while (queue.length) await run(queue.shift()); }));
await browser.close();
fs.writeFileSync("report.json", JSON.stringify(report, null, 1));
const bad = report.filter((r) => r.fatal || r.overflow || r.errs?.length);
console.log(`checked ${report.length} page/width/theme combos; problems: ${bad.length}`);
const seen = new Set();
for (const b of bad) { const k = JSON.stringify([b.path, b.fatal, b.overflow, b.errs, b.offenders]); if (seen.has(k)) continue; seen.add(k); console.log(b.path, `@${b.w}/${b.theme}`, b.fatal ?? "", b.overflow ? `OVERFLOW sw=${b.sw} vw=${b.vw} ${b.offenders.join(" | ")}` : "", b.errs?.slice(0, 3).join(" ; ") ?? ""); }
