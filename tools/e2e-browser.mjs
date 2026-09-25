/**
 * End-to-end, in a real browser.
 *
 * Drives Chromium against the running stack: Next on :3000, which proxies /v1 to
 * FastAPI on :8000, which talks to Postgres and Redis, with the worker generating
 * frames into object storage. Nothing here is mocked.
 *
 * It also fails on any console error or failed network request, because a page
 * that renders while throwing is not working.
 *
 *   node tools/e2e-browser.mjs            headless
 *   HEADED=1 node tools/e2e-browser.mjs   watch it happen
 */

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const BASE = process.env.BASE_URL ?? "http://127.0.0.1:3000";
const SHOTS = "tools/e2e-screens";
mkdirSync(SHOTS, { recursive: true });

let passed = 0;
const failures = [];
const consoleErrors = [];
const netFailures = [];

function check(name, condition, detail = "") {
  if (condition) {
    passed += 1;
    console.log(`  \x1b[32mPASS\x1b[0m ${name}${detail ? `  ${detail}` : ""}`);
  } else {
    failures.push(name);
    console.log(`  \x1b[31mFAIL\x1b[0m ${name}${detail ? `  ${detail}` : ""}`);
  }
}

function section(title) {
  console.log(`\n\x1b[1m${title}\x1b[0m`);
}

const shot = (page, name) =>
  page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: false });

async function main() {
  const browser = await chromium.launch({ headless: !process.env.HEADED });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200));
  });
  page.on("requestfailed", (r) => {
    // Aborted requests are the debounce and cursor cancellation working.
    const err = r.failure()?.errorText ?? "";
    if (!err.includes("ERR_ABORTED")) {
      netFailures.push(`${r.method()} ${r.url().replace(BASE, "")} ${err}`);
    }
  });

  // ── 1. the wall, served from Postgres ────────────────────────────────
  section("1. The wall renders real data from Postgres");
  await page.goto(BASE, { waitUntil: "networkidle" });

  const cards = page.getByTestId("wall-card");
  await cards.first().waitFor({ timeout: 20000 });
  const cardCount = await cards.count();
  check("wall renders cards", cardCount >= 10, `${cardCount} cards`);

  // Frames must actually decode, not just have a src.
  const decoded = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid="frame"] img'))
      .filter((i) => i.complete && i.naturalWidth > 0).length,
  );
  check("frames decode as real images", decoded >= 4, `${decoded} decoded`);

  const firstSrc = await page.locator('[data-testid="frame"] img').first().getAttribute("src");
  check("frames are served from our own route", (firstSrc ?? "").startsWith("/v1/frames/"), firstSrc ?? "");
  check(
    "no upstream URL reaches the browser",
    !(firstSrc ?? "").includes("pollinations"),
  );

  const prompt = await page.getByTestId("wall-card-prompt").first().textContent();
  check("every card carries its prompt", (prompt ?? "").trim().length > 10, `"${(prompt ?? "").slice(0, 44)}…"`);
  await shot(page, "01-wall");

  // ── 2. anonymous session ─────────────────────────────────────────────
  section("2. A stranger gets a real account and credits");
  await page.getByTestId("nav-credits").waitFor();
  const creditsText = await page.getByTestId("credits-value").textContent();
  check("credits show in the nav", creditsText?.trim() === "40", `"${creditsText?.trim()}"`);

  const cookies = await context.cookies();
  const access = cookies.find((c) => c.name === "dr_at");
  const refresh = cookies.find((c) => c.name === "dr_rt");
  check("access cookie is set", Boolean(access));
  check("refresh cookie is set", Boolean(refresh));
  check("session cookies are httpOnly", Boolean(access?.httpOnly && refresh?.httpOnly));

  // ── 3. search, debounced ─────────────────────────────────────────────
  section("3. Search is debounced and hits the server");
  const searchCalls = [];
  page.on("request", (r) => {
    if (r.url().includes("/v1/wall") && r.url().includes("q=")) searchCalls.push(r.url());
  });
  await page.getByTestId("wall-search").fill("");
  await page.getByTestId("wall-search").pressSequentially("courier", { delay: 40 });
  await page.waitForTimeout(1200);
  check(
    "typing 7 characters made at most 2 requests",
    searchCalls.length <= 2,
    `${searchCalls.length} request(s)`,
  );
  const searchCount = await page.getByTestId("wall-card").count();
  check("search narrows the wall", searchCount >= 1 && searchCount < cardCount, `${searchCount} of ${cardCount}`);
  await shot(page, "02-search");

  // ── 4. remix prefills the composer ───────────────────────────────────
  section("4. Remix loads the exact parameters");
  await page.getByTestId("wall-search").fill("");
  await page.waitForTimeout(700);
  const card = page.getByTestId("wall-card").first();
  const remixPrompt = (await card.getByTestId("wall-card-prompt").textContent())?.trim() ?? "";
  await card.hover();
  await card.getByTestId("wall-card-remix").click();
  await page.waitForURL(/\/create\?/, { timeout: 15000 });
  const textarea = page.locator("textarea").first();
  await textarea.waitFor();
  const loadedPrompt = (await textarea.inputValue()).trim();
  check("composer opens with the prompt", loadedPrompt === remixPrompt, `"${loadedPrompt.slice(0, 40)}…"`);
  await shot(page, "03-remix");

  // ── 5. cost before spending ──────────────────────────────────────────
  section("5. Cost is itemised before it is spent");
  await textarea.fill("a lighthouse keeper mending a net on a grey morning");
  await page.waitForTimeout(800);
  const costText = (await page.getByTestId("develop-cost").textContent())?.trim() ?? "";
  check("the button shows a cost", /^\d+ cr$/.test(costText), `"${costText}"`);
  const quoted = Number(costText.replace(" cr", ""));
  check("the cost is a real number of credits", quoted > 0, `${quoted} cr`);

  // ── 6. submit, and watch the job land over SSE ────────────────────────
  section("6. Submit debits, queues, generates, and streams back");
  const creditsBefore = Number((await page.getByTestId("credits-value").textContent())?.trim());

  await page.getByTestId("develop").click();
  await page.getByTestId("job-tray").waitFor({ timeout: 20000 });
  check("the job tray appears", true);

  const trayJob = page.getByTestId("tray-job").first();
  await trayJob.waitFor();
  check("a job row is in the tray", await trayJob.isVisible());
  await shot(page, "04-submitted");

  // Credits drop by the quoted amount, from the server.
  await page.waitForFunction(
    (before) => {
      const el = document.querySelector('[data-testid="credits-value"]');
      return el && Number(el.textContent.trim()) < before;
    },
    creditsBefore,
    { timeout: 20000 },
  );
  const creditsAfter = Number((await page.getByTestId("credits-value").textContent())?.trim());
  check(
    "credits were debited by the quoted amount",
    creditsBefore - creditsAfter === quoted,
    `${creditsBefore} -> ${creditsAfter} (quoted ${quoted})`,
  );

  // The worker generates for real; SSE drives the UI to a terminal state.
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[data-testid="tray-job"]');
      const s = el?.getAttribute("data-job-status");
      return s && ["succeeded", "partial", "failed"].includes(s);
    },
    null,
    { timeout: 180000 },
  );
  const finalStatus = await trayJob.getAttribute("data-job-status");
  check("the job reached a terminal state via SSE", Boolean(finalStatus), finalStatus ?? "");
  check("the job succeeded", finalStatus === "succeeded", finalStatus ?? "");

  await page.waitForTimeout(1500);
  const resultReady = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid="result-tile"] img'))
      .filter((i) => i.complete && i.naturalWidth > 0).length,
  );
  check("the generated frame renders in the page", resultReady >= 1, `${resultReady} frame(s)`);
  await shot(page, "05-generated");

  // ── 7. publish, and it reaches the wall ──────────────────────────────
  section("7. Publishing puts it on the wall");
  const publish = page.getByTestId("publish-toggle").first();
  await publish.click();
  await page.waitForTimeout(1200);
  const label = (await publish.textContent())?.trim();
  check("the tile reports it is on the wall", label === "on the wall", `"${label}"`);

  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.getByTestId("wall-search").fill("lighthouse keeper mending");
  await page.waitForTimeout(1400);
  const mine = await page.getByTestId("wall-card").count();
  check("the published frame is on the public wall", mine >= 1, `${mine} match(es)`);
  await shot(page, "06-published");

  // ── 8. library ───────────────────────────────────────────────────────
  section("8. The contact sheet shows your own work");
  await page.goto(`${BASE}/library`, { waitUntil: "networkidle" });
  await page.getByTestId("library-card").first().waitFor({ timeout: 20000 });
  const libCount = await page.getByTestId("library-card").count();
  check("library lists the generated frames", libCount >= 1, `${libCount} item(s)`);
  await shot(page, "07-library");

  // ── 9. the ledger ────────────────────────────────────────────────────
  section("9. The ledger accounts for every credit");
  await page.goto(`${BASE}/pricing`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  const body = await page.locator("body").textContent();
  check("ledger shows the signup grant", (body ?? "").includes("signup"), "");
  check("ledger shows the job debit", (body ?? "").includes("job"), "");
  await shot(page, "08-ledger");

  // ── 10. presets, in full ─────────────────────────────────────────────
  section("10. Presets are readable in full");
  await page.goto(`${BASE}/presets`, { waitUntil: "networkidle" });
  await page.getByTestId("preset-card").first().waitFor({ timeout: 20000 });
  const presetCount = await page.getByTestId("preset-card").count();
  check("all 18 presets render", presetCount === 18, `${presetCount} presets`);
  await page.getByText("the template, in full").first().click();
  const template = await page.getByTestId("preset-template").first().textContent();
  check("the template is shown verbatim", (template ?? "").includes("{prompt}"), "");
  await shot(page, "09-presets");

  // ── 11. hygiene ──────────────────────────────────────────────────────
  section("11. No console errors, no failed requests");
  check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
  check("no failed network requests", netFailures.length === 0, netFailures.slice(0, 3).join(" | "));

  await browser.close();

  console.log(
    `\n\x1b[1m${passed} passed, ${failures.length} failed\x1b[0m  · screenshots in ${SHOTS}/`,
  );
  if (failures.length) {
    console.log("failed:\n  - " + failures.join("\n  - "));
    process.exit(1);
  }
}

main().catch((err) => {
  console.error("\ne2e crashed:", err.message);
  process.exit(1);
});
