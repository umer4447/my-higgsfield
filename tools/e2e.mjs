import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await b.newContext({ viewport:{width:1440,height:1000} });
await ctx.route('**image.pollinations.ai/**', r => r.fulfill({ status:200, contentType:'image/svg+xml',
  body:`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#242429"/><text x="50%" y="50%" fill="#6b6965" font-family="monospace" font-size="22" text-anchor="middle">FRAME</text></svg>` }));
const p = await ctx.newPage();
const errs = [];
p.on('console', m => m.type()==='error' && errs.push(m.text()));
p.on('pageerror', e => errs.push('PAGEERROR: '+e.message));

await p.goto('http://localhost:3100/create', { waitUntil:'networkidle' });
await p.waitForSelector('textarea');
await p.fill('textarea', 'a lighthouse keeper crossing a causeway at high tide');
await p.click('text=Portra Soft');
await p.click('button:has-text("Develop")');
await p.waitForTimeout(3500);
await p.screenshot({ path:'/tmp/e2e_1_result.png' });
console.log('credits after:', await p.textContent('header .mono'));
// open first result
const link = await p.$('a[href^="/a/"]');
await link.click();
await p.waitForTimeout(2500);
await p.screenshot({ path:'/tmp/e2e_2_asset.png', fullPage:true });
// remix
await p.click('text=Remix these settings');
await p.waitForTimeout(2000);
const val = await p.inputValue('textarea');
console.log('remix prompt:', JSON.stringify(val.slice(0,50)));
// library
await p.goto('http://localhost:3100/library', { waitUntil:'networkidle' });
await p.waitForTimeout(1800);
await p.screenshot({ path:'/tmp/e2e_3_library.png' });
// wall hover
await p.goto('http://localhost:3100/', { waitUntil:'networkidle' });
await p.waitForTimeout(1500);
const card = await p.$('.group');
await card.hover();
await p.waitForTimeout(600);
await p.screenshot({ path:'/tmp/e2e_4_wallhover.png' });
console.log('ERRORS:', errs.length ? errs.slice(0,8) : 'none');
await b.close();
