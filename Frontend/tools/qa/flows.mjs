import puppeteer from "puppeteer-core";
const B = "http://localhost:3000";
const b = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", args: ["--no-sandbox", "--disable-gpu"], headless: "new" });
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function flow(name, fn, opts = {}) {
  const ctx = await b.createBrowserContext();
  const p = await ctx.newPage();
  await p.setViewport({ width: opts.w ?? 1280, height: 900, isMobile: (opts.w ?? 1280) < 500 });
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message.slice(0, 120)));
  try { const note = await fn(p); results.push({ name, ok: true, note, errs }); }
  catch (e) { results.push({ name, ok: false, note: e.message.slice(0, 200), errs }); try { await p.screenshot({ path: `shots/flow-${name.replace(/\W+/g, "_")}.png` }); } catch {} }
  await ctx.close();
}
const text = (p, sel) => p.$eval(sel, (e) => e.textContent);
const expect = (c, m) => { if (!c) throw new Error(m); };
const ck = (p) => p.cookies(B).then((c) => c.map((x) => x.name));

await flow("demo farmer login -> dashboard + demo badge + tour starts", async (p) => {
  await p.goto(B + "/login", { waitUntil: "networkidle0" });
  await p.locator("::-p-text(Try demo farmer)").click();
  await p.waitForFunction(() => location.pathname === "/farmer/dashboard", { timeout: 15000 });
  await sleep(800);
  expect((await ck(p)).includes("emandi_session"), "session hint cookie not set");
  expect(await p.evaluate(() => document.body.innerText.includes("Demo mode")), "no Demo mode badge");
  const dlg = await p.$('[role="dialog"]');
  expect(!!dlg, "tour dialog not shown");
  return await p.$eval('[role="dialog"] h2', (e) => e.textContent);
});

await flow("tour: next navigates, spotlight present, Esc skips", async (p) => {
  await p.goto(B + "/login", { waitUntil: "networkidle0" });
  await p.locator("::-p-text(Try demo farmer)").click();
  await p.waitForFunction(() => location.pathname === "/farmer/dashboard", { timeout: 15000 });
  await sleep(1200);
  const spot = await p.evaluate(() => [...document.querySelectorAll("div")].some((d) => d.style.boxShadow.includes("9999px")));
  expect(spot, "no spotlight element on step 1");
  await p.locator('[role="dialog"] button ::-p-text(Next)').click(); await sleep(2200);
  expect(new URL(p.url()).pathname === "/farmer/sell", "step 2 did not navigate to /farmer/sell, at " + p.url());
  await p.locator('[role="dialog"] button ::-p-text(Next)').click(); await sleep(2800);   // upload-zone step
  await p.locator('[role="dialog"] button ::-p-text(Next)').click(); await sleep(3200);   // grading step (target absent -> fallback)
  const hint = await p.$eval('[role="dialog"]', (e) => e.textContent);
  await p.keyboard.press("Escape"); await sleep(80);
  expect(await p.evaluate(() => { const d = document.querySelector('[role="dialog"]'); return !d || d.closest("[inert]") !== null; }), "tour still interactive right after Esc");
  await sleep(700);
  expect(!(await p.$('[role="dialog"]')), "Esc did not close (unmount) the tour");
  return "reached grading step; fallback text: " + (hint.includes("Highlight unavailable") ? "yes" : "no (target found)");
});

await flow("sell wizard end-to-end with sample crop", async (p) => {
  await p.setCookie({ name: "mockrole", value: "farmer", url: B }, { name: "emandi_session", value: "1", url: B });
  await p.goto(B + "/farmer/sell", { waitUntil: "networkidle0" });
  await p.locator("::-p-text(Tomato)").click();
  await p.waitForFunction(() => !document.querySelector('button[disabled]:not([aria-label])') || [...document.querySelectorAll("button")].find((b) => /^Continue$/.test(b.textContent) && !b.disabled), { timeout: 10000 });
  const cont = () => p.locator("button ::-p-text(Continue)").click();
  await sleep(600); await cont();
  await p.type("#crop", "Tomato"); await cont();
  await p.type("#quantityKg", "500"); await cont();
  await p.type("#location", "Hosur"); await cont();
  await p.waitForSelector('[aria-label="Grade A"]', { timeout: 15000 });
  await p.locator("::-p-text(See price suggestion)").click();
  await p.waitForFunction(() => document.body.innerText.includes("Reference range"), { timeout: 8000 });
  await cont();
  await p.locator("::-p-text(Looks good)").click();
  await p.locator("::-p-text(Publish listing)").click();
  await p.waitForFunction(() => document.body.innerText.includes("Listing published"), { timeout: 8000 });
  return "published";
});

await flow("protected route -> login?next -> demo login returns to original page", async (p) => {
  await p.goto(B + "/farmer/orders", { waitUntil: "networkidle0" });
  expect(p.url().includes("/login") && p.url().includes("next=%2Ffarmer%2Forders"), "not redirected with next: " + p.url());
  await p.locator("::-p-text(Try demo farmer)").click();
  await p.waitForFunction(() => location.pathname === "/farmer/orders", { timeout: 15000 });
  return "landed on " + new URL(p.url()).pathname;
});

await flow("open redirect blocked", async (p) => {
  await p.goto(B + "/login?next=//evil.com", { waitUntil: "networkidle0" });
  await p.locator("::-p-text(Try demo buyer)").click();
  await p.waitForFunction(() => location.pathname.startsWith("/buyer"), { timeout: 15000 });
  return "stayed on " + new URL(p.url()).origin + new URL(p.url()).pathname;
});

await flow("wrong role is redirected to own home", async (p) => {
  await p.setCookie({ name: "mockrole", value: "buyer", url: B }, { name: "emandi_session", value: "1", url: B });
  await p.goto(B + "/farmer/dashboard", { waitUntil: "networkidle0" });
  await p.waitForFunction(() => location.pathname === "/buyer/marketplace", { timeout: 10000 });
  return "redirected to /buyer/marketplace";
});

await flow("theme choice persists across reload", async (p) => {
  await p.setCookie({ name: "mockrole", value: "farmer", url: B }, { name: "emandi_session", value: "1", url: B });
  await p.goto(B + "/farmer/dashboard", { waitUntil: "networkidle0" });
  await p.click('button[aria-label="Change theme"]'); await sleep(300);
  await p.locator('[role="menuitem"] ::-p-text(Dark)').click(); await sleep(400);
  expect(await p.evaluate(() => document.documentElement.classList.contains("dark")), "dark class not applied");
  await p.reload({ waitUntil: "networkidle0" });
  expect(await p.evaluate(() => document.documentElement.classList.contains("dark")), "dark did not persist");
  return "dark persisted";
});

await flow("mobile: drawer opens with nav + preferences, logo not clipped", async (p) => {
  await p.setCookie({ name: "mockrole", value: "farmer", url: B }, { name: "emandi_session", value: "1", url: B });
  await p.goto(B + "/farmer/dashboard", { waitUntil: "networkidle0" });
  await p.click('button[aria-label="Open menu"]'); await sleep(600);
  const top = await p.evaluate(() => { const l = document.querySelector('[role="dialog"] svg'); return l ? Math.round(l.getBoundingClientRect().top) : -1; });
  expect(top >= 12, "drawer logo clipped at top=" + top);
  expect(await p.evaluate(() => !!document.querySelector('[role="dialog"] button[aria-label="Change theme"]')), "no theme control in drawer");
  await p.screenshot({ path: "shots/drawer-fixed.png" });
  return "logo top=" + top + "px";
}, { w: 390 });

await flow("language persists across reload without hydration errors", async (p) => {
  const msgs = [];
  p.on("console", (m) => m.type() === "error" && msgs.push(m.text().slice(0, 120)));
  await p.setCookie({ name: "mockrole", value: "farmer", url: B }, { name: "emandi_session", value: "1", url: B });
  await p.goto(B + "/farmer/dashboard", { waitUntil: "networkidle0" });
  await p.click('button[aria-label="Change language"]'); await sleep(300);
  await p.locator('[role="menuitem"] ::-p-text(हिन्दी)').click(); await sleep(500);
  expect(await p.evaluate(() => document.documentElement.lang) === "hi", "html lang not hi");
  await p.goto(B + "/", { waitUntil: "networkidle0" }); await sleep(800);
  const lang = await p.evaluate(() => document.documentElement.lang);
  const h1 = await p.$eval("h1", (e) => e.textContent);
  expect(lang === "hi" && /भरोसेमंद/.test(h1), "language not restored on public page: " + lang + " / " + h1);
  return "restored hi; console errors: " + (msgs.filter((m) => !/WebSocket|Failed to load/.test(m)).length);
});

await b.close();
for (const r of results) console.log((r.ok ? "PASS" : "FAIL") + "  " + r.name + "\n      " + r.note + (r.errs.length ? "\n      pageerrors: " + r.errs.join(" | ") : ""));
