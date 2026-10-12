import puppeteer from "puppeteer-core";
const B = "http://localhost:3000";
const b = await puppeteer.launch({ executablePath: process.env.CHROME ?? "/usr/bin/google-chrome", args: ["--no-sandbox", "--disable-gpu"], headless: "new" });
const p = await b.newPage(); await p.setViewport({ width: 1440, height: 900 });
await p.evaluateOnNewDocument(() => localStorage.setItem("emandi-theme", "dark"));
await p.setCookie({ name: "mockrole", value: "farmer", url: B }, { name: "emandi_session", value: "1", url: B });
await p.goto(B + "/farmer/dashboard", { waitUntil: "networkidle0" }); await new Promise((r) => setTimeout(r, 800));
async function record(label, clickSel) {
  await p.evaluate(() => { window.__s = []; window.__stop = false; let last = performance.now();
    const f = (now) => { const a = document.querySelector("[data-sidebar]"); const link = a.querySelector("nav a svg"); const span = a.querySelector("nav a span");
      const main = document.querySelector("#main-content");
      window.__s.push({ now, dt: now - last, w: a.getBoundingClientRect().width, icon: link.getBoundingClientRect().left, lab: +getComputedStyle(span).opacity, labW: span.getBoundingClientRect().width, mainL: main.getBoundingClientRect().left });
      last = now; if (!window.__stop) requestAnimationFrame(f); }; requestAnimationFrame(f); });
  await new Promise((r) => setTimeout(r, 120));
  await p.click(clickSel); await new Promise((r) => setTimeout(r, 700));
  const s = await p.evaluate(() => { window.__stop = true; return window.__s; });
  const t0 = s.find((x, i) => i && x.w !== s[i - 1].w)?.now ?? s[0].now; const moving = s.filter((x) => x.now >= t0 - 20);
  const w0 = moving[0].w, w1 = moving[moving.length - 1].w; const end = moving.find((x, i) => Math.abs(x.w - w1) < 0.5 && i > 2);
  const dir = Math.sign(w1 - w0); let nonMono = 0; for (let i = 1; i < moving.length; i++) if ((moving[i].w - moving[i - 1].w) * dir < -0.01) nonMono++;
  const iconDrift = Math.max(...moving.map((x) => x.icon)) - Math.min(...moving.map((x) => x.icon));
  const steps = moving.slice(0, 25).map((x) => x.w.toFixed(0)).join(",");
  const dts = moving.map((x) => x.dt).filter((d) => d < 1000);
  console.log(`${label}: width ${w0.toFixed(0)}→${w1.toFixed(0)}px in ~${end ? (end.now - t0).toFixed(0) : "?"}ms | non-monotonic frames: ${nonMono} | icon x drift: ${iconDrift.toFixed(2)}px | worst frame ${Math.max(...dts).toFixed(0)}ms | content left edge ${moving[0].mainL.toFixed(0)}→${moving[moving.length - 1].mainL.toFixed(0)}`);
  console.log("   width per frame:", steps);
  return moving;
}
await record("collapse", 'button[aria-label="Collapse sidebar"]');
await record("expand  ", 'button[aria-label="Expand sidebar"]');
await b.close();
