#!/usr/bin/env node
/**
 * Bake the wall.
 *
 * The seed feed is 24 real generations. Generating them live, per visitor, is
 * what put "frame lost" all over the page: the upstream endpoint rate-limits per
 * IP, and every visitor was spending their own allowance on content that is
 * identical for everybody.
 *
 * So they are generated once, here, and committed to public/wall. The wall then
 * paints instantly for everyone, costs nothing and cannot fail — while anything
 * a user actually composes still goes through /api/frame and is genuinely
 * generated on demand.
 *
 *   npm run bake:wall          bake anything missing
 *   FORCE=1 npm run bake:wall  re-bake everything
 *
 * Needs no dev server: it reads tools/wall-manifest.json (regenerate that from
 * /api/wall-manifest if the seed list changes) and talks to the generator
 * directly, one request at a time, slowly, because that is the whole point.
 */

import { mkdir, writeFile, access, readFile } from "node:fs/promises";
import { join } from "node:path";

const OUT = join(process.cwd(), "public", "wall");
const MANIFEST = join(process.cwd(), "tools", "wall-manifest.json");
const GAP_MS = Number(process.env.GAP_MS ?? 6000);
const ATTEMPTS = 6;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const exists = (p) => access(p).then(() => true).catch(() => false);

const manifest = JSON.parse(await readFile(MANIFEST, "utf8"));
await mkdir(OUT, { recursive: true });

console.log(
  `baking ${manifest.length} frames into public/wall, ${GAP_MS / 1000}s apart\n`,
);

let made = 0;
let skipped = 0;
const failures = [];

for (const [i, item] of manifest.entries()) {
  const file = join(OUT, `${item.id}.jpg`);
  const tag = `[${String(i + 1).padStart(2, "0")}/${manifest.length}] ${item.id}`;

  if (!process.env.FORCE && (await exists(file))) {
    console.log(`${tag}  skip (already baked)`);
    skipped += 1;
    continue;
  }

  let ok = false;
  for (let attempt = 1; attempt <= ATTEMPTS && !ok; attempt++) {
    const t0 = Date.now();
    try {
      const res = await fetch(item.upstream, {
        headers: { accept: "image/*" },
        signal: AbortSignal.timeout(90_000),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.byteLength < 2048)
        throw new Error(`suspiciously small (${buf.byteLength}B)`);
      await writeFile(file, buf);
      console.log(
        `${tag}  ${(buf.byteLength / 1024).toFixed(0)}KB in ${(
          (Date.now() - t0) / 1000
        ).toFixed(1)}s`,
      );
      ok = true;
      made += 1;
    } catch (e) {
      // 503 from this endpoint means "slow down", so slowing down is the remedy
      const wait = 5000 * attempt;
      console.log(
        `${tag}  attempt ${attempt} failed (${e.message}) — waiting ${wait / 1000}s`,
      );
      if (attempt < ATTEMPTS) await sleep(wait);
    }
  }

  if (!ok) failures.push(`${item.id} — ${item.prompt}`);
  await sleep(GAP_MS);
}

console.log(`\nbaked ${made}, skipped ${skipped}, failed ${failures.length}`);
if (failures.length) {
  console.log("\nstill missing:");
  failures.forEach((f) => console.log("  " + f));
  console.log("\nre-run to retry just those — baked frames are skipped.");
  process.exit(1);
}
