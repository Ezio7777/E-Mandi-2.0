import puppeteer from "puppeteer-core";
const B="http://localhost:3000";
const b=await puppeteer.launch({executablePath: process.env.CHROME ?? "/usr/bin/google-chrome",args:["--no-sandbox","--disable-gpu"],headless:"new"});
const targets=[["public","/login"],["public","/"],["farmer","/farmer/dashboard"],["buyer","/buyer/marketplace"],["farmer","/farmer/sell"]];
let bad=0, total=0;
for (const theme of ["light","dark"]) for (const [role,path] of targets) {
  const p=await b.newPage(); await p.setViewport({width:1280,height:900});
  await p.evaluateOnNewDocument((t)=>localStorage.setItem("emandi-theme",t),theme);
  if(role!=="public") await p.setCookie({name:"mockrole",value:role,url:B},{name:"emandi_session",value:"1",url:B});
  await p.goto(B+path,{waitUntil:"networkidle0"}); await new Promise(r=>setTimeout(r,500));
  const seen=new Set(); let stuck=0;
  for (let i=0;i<40;i++) {
    await p.keyboard.press("Tab");
    const r=await p.evaluate(()=>{const e=document.activeElement; if(!e||e===document.body) return null; const cs=getComputedStyle(e); const rect=e.getBoundingClientRect();
      const ring=(cs.boxShadow&&cs.boxShadow!=="none")||(cs.outlineStyle!=="none"&&parseFloat(cs.outlineWidth)>0);
      return {id:e.tagName.toLowerCase()+"."+(e.getAttribute("aria-label")||e.textContent||"").trim().slice(0,24),ring,vis:rect.width>0&&rect.height>0};});
    if(!r){continue;} if(seen.has(r.id)){ if(++stuck>3)break; continue;} seen.add(r.id);
    if(r.vis){ total++; if(!r.ring){ bad++; console.log("NO FOCUS RING:",theme,path,r.id); } }
  }
  await p.close();
}
await b.close(); console.log(`focusable stops checked: ${total}, without visible focus indicator: ${bad}`);
