import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await b.newContext({ viewport:{width:1440,height:900} });
await ctx.route('**image.pollinations.ai/**', r => r.fulfill({ status:200, contentType:'image/svg+xml',
  body:`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#242429"/></svg>` }));
const p = await ctx.newPage();
const errs=[]; p.on('pageerror', e=>errs.push(e.message));
await p.goto('http://localhost:3100/', { waitUntil:'networkidle' });
await p.keyboard.press('Control+k');
await p.waitForTimeout(500);
await p.keyboard.type('sodium');
await p.waitForTimeout(400);
await p.screenshot({ path:'/tmp/palette.png' });
await p.keyboard.press('Enter');
await p.waitForTimeout(1800);
console.log('url after enter:', p.url());
console.log('errors:', errs);
await b.close();
