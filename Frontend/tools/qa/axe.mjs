import puppeteer from "puppeteer-core";
import fs from "node:fs";
const B = "http://localhost:3000";
const axeSrc = fs.readFileSync("node_modules/axe-core/axe.min.js", "utf8");
const routes = {
  public: ["/", "/how-it-works", "/login", "/demo"],
  farmer: ["/farmer/dashboard", "/farmer/sell", "/farmer/listings", "/farmer/listings/l1", "/farmer/orders/o1", "/farmer/assistant", "/farmer/profile"],
  buyer: ["/buyer/marketplace", "/buyer/marketplace/l1", "/buyer/requirements/new", "/buyer/matches", "/buyer/orders/o2"],
  admin: ["/admin/analytics", "/admin/users", "/admin/risk", "/admin/approvals", "/admin/grading"],
};
const themes = (process.env.THEMES ?? "light,dark").split(",");
const b = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", args: ["--no-sandbox", "--disable-gpu"], headless: "new" });
const found = new Map();
for (const [role, list] of Object.entries(routes)) for (const path of list) for (const theme of themes) {
  const p = await b.newPage();
  await p.setViewport({ width: 390, height: 900, isMobile: true, hasTouch: true });
  await p.evaluateOnNewDocument((t) => localStorage.setItem("emandi-theme", t), theme);
  if (role !== "public") await p.setCookie({ name: "mockrole", value: role, url: B }, { name: "emandi_session", value: "1", url: B });
  try {
    await p.goto(B + path, { waitUntil: "networkidle0", timeout: 30000 });
    await new Promise((r) => setTimeout(r, 500));
    await p.evaluate(axeSrc);
    const res = await p.evaluate(() => axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] } }));
    for (const v of res.violations) {
      const key = `${v.id}|${v.impact}`;
      const e = found.get(key) ?? { id: v.id, impact: v.impact, help: v.help, where: new Set(), sample: new Set() };
      e.where.add(`${path}(${theme})`);
      v.nodes.slice(0, 2).forEach((n) => e.sample.add(n.target.join(" ") + " :: " + (n.any[0]?.message ?? n.all[0]?.message ?? "").slice(0, 110)));
      found.set(key, e);
    }
  } catch (e) { console.log("FAIL", path, theme, e.message.slice(0, 80)); }
  try { await p.close(); } catch {}
}
await b.close();
const order = { critical: 0, serious: 1, moderate: 2, minor: 3 };
const list = [...found.values()].sort((a, b) => order[a.impact] - order[b.impact]);
console.log("distinct violation types:", list.length);
for (const v of list) console.log(`\n[${v.impact}] ${v.id}: ${v.help}\n  pages: ${[...v.where].slice(0, 5).join(", ")}${v.where.size > 5 ? ` (+${v.where.size - 5})` : ""}\n  e.g. ${[...v.sample].slice(0, 2).join("\n       ")}`);
