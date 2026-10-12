import puppeteer from "puppeteer-core";
const B="http://localhost:3000";
const b=await puppeteer.launch({executablePath: process.env.CHROME ?? "/usr/bin/google-chrome",args:["--no-sandbox","--disable-gpu"],headless:"new"});
const p=await b.newPage(); await p.setViewport({width:390,height:844,isMobile:true,hasTouch:true});
await p.setCookie({name:"mockrole",value:"farmer",url:B},{name:"emandi_session",value:"1",url:B});
await p.goto(B+"/farmer/dashboard",{waitUntil:"networkidle0"}); await new Promise(r=>setTimeout(r,700));
async function rec(label, action){
  await p.evaluate(()=>{window.__d=[];window.__stop=false;const f=(n)=>{const d=document.querySelector('[role="dialog"]');const o=d?.parentElement?.previousElementSibling;window.__d.push({n,x:d?d.getBoundingClientRect().left:null,ov:o?+getComputedStyle(o).opacity:null});if(!window.__stop)requestAnimationFrame(f)};requestAnimationFrame(f)});
  await new Promise(r=>setTimeout(r,100)); await action(); await new Promise(r=>setTimeout(r,700));
  const d=await p.evaluate(()=>{window.__stop=true;return window.__d});
  const xs=d.filter(f=>f.x!==null); const first=xs[0]?.n; const mono=xs.every((f,i)=>i===0||f.x>=xs[i-1].x-0.01);
  const seq=xs.slice(0,22).map(f=>Math.round(f.x)).join(",");
  console.log(`${label}: ${xs.length} frames with drawer, starts x=${Math.round(xs[0]?.x)}, ends x=${Math.round(xs[xs.length-1]?.x)}, monotonic=${label==="open"?mono:"n/a"}\n   x per frame: ${seq}`);
}
await rec("open", ()=>p.click('button[aria-label="Open menu"]'));
await rec("close", ()=>p.keyboard.press("Escape"));
await b.close();
