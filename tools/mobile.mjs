import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await b.newContext({ viewport:{width:390,height:844}, deviceScaleFactor:2, isMobile:true, hasTouch:true });
await ctx.route('**image.pollinations.ai/**', r => r.fulfill({ status:200, contentType:'image/svg+xml',
  body:`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#242429"/><text x="50%" y="50%" fill="#6b6965" font-family="monospace" font-size="30" text-anchor="middle">FRAME</text></svg>` }));
const p = await ctx.newPage();
for (const u of process.argv.slice(2)) {
  await p.goto('http://localhost:3100'+u, { waitUntil:'networkidle' }).catch(()=>{});
  await p.waitForTimeout(1200);
  const overflow = await p.evaluate(()=>document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log(u, 'h-overflow:', overflow);
  await p.screenshot({ path:`/tmp/m_${u.replace(/[^a-z]/gi,'_')||'home'}.png` });
}
await b.close();
