import { chromium } from 'playwright';
const pages = process.argv.slice(2);
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await b.newContext({ viewport:{width:1440,height:1000}, deviceScaleFactor:1 });
// the image endpoint is unreachable from this container; paint a neutral tile so
// layout can be judged without pretending the frames loaded
await ctx.route('**image.pollinations.ai/**', r => r.fulfill({ status:200, contentType:'image/svg+xml',
  body:`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#1d1d21"/><rect x="0" y="0" width="600" height="800" fill="url(#g)"/><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2a2a30"/><stop offset="1" stop-color="#141417"/></linearGradient></defs><text x="50%" y="50%" fill="#55555c" font-family="monospace" font-size="20" text-anchor="middle">FRAME</text></svg>` }));
const p = await ctx.newPage();
for (const url of pages) {
  const name = url.replace(/[^a-z0-9]/gi,'_') || 'home';
  await p.goto('http://localhost:3100'+url, { waitUntil:'networkidle' }).catch(()=>{});
  await p.waitForTimeout(1200);
  await p.screenshot({ path:`/tmp/ui_${name}.png`, fullPage:false });
  await p.screenshot({ path:`/tmp/uifull_${name}.png`, fullPage:true });
  console.log('shot', url);
}
await b.close();
