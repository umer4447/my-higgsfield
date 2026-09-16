import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await b.newContext({ viewport:{width:1200,height:800} });
await ctx.route('**image.pollinations.ai/**', r => r.fulfill({ status:200, contentType:'image/svg+xml',
  body:`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400"><rect width="600" height="400" fill="#333"/><circle cx="300" cy="200" r="60" fill="#ff5a1f"/></svg>` }));
const p = await ctx.newPage();
await p.goto('http://localhost:3100/a/wall-02', { waitUntil:'networkidle' });
await p.waitForTimeout(2000);
const read = () => p.evaluate(() => {
  const img = document.querySelector('img.mv');
  if (!img) return null;
  return getComputedStyle(img).transform;
});
const a = await read(); await p.waitForTimeout(1400); const c = await read();
console.log('t0:', a); console.log('t1:', c); console.log('ANIMATING:', a !== c);
await b.close();
