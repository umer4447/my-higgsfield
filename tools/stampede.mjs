import { chromium } from 'playwright';
const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
const ctx = await b.newContext({ viewport:{width:1440,height:1000} });

// Simulate the real failure mode: the endpoint refuses anything past 3 concurrent,
// and each accepted request takes ~1.5s.
let inFlight = 0, peak = 0, refused = 0, served = 0;
await ctx.route('**image.pollinations.ai/**', async r => {
  inFlight++; peak = Math.max(peak, inFlight);
  if (inFlight > 3) { inFlight--; refused++; return r.fulfill({ status: 503, body: 'busy' }); }
  await new Promise(x => setTimeout(x, 1500));
  inFlight--; served++;
  r.fulfill({ status:200, contentType:'image/svg+xml',
    body:`<svg xmlns="http://www.w3.org/2000/svg" width="400" height="500"><rect width="400" height="500" fill="#2a2a30"/></svg>` });
});

const p = await ctx.newPage();
await p.goto('http://localhost:3100/', { waitUntil:'domcontentloaded' });
await p.waitForTimeout(25000);
const counts = await p.evaluate(() => ({
  lost: document.body.innerText.split('frame lost').length - 1,
  developing: document.body.innerText.toLowerCase().split('developing').length - 1,
  imgs: document.querySelectorAll('img').length,
}));
console.log({ peakConcurrent: peak, served, refused, ...counts });
await b.close();
