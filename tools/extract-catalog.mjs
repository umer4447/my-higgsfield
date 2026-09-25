// Extract the catalog from the frontend TypeScript into prisma/seed/catalog.json.
//
// The seed reads that JSON. Transcribing 18 presets by hand is how a template
// loses its {prompt} slot; this keeps the seed and the frontend catalog from
// drifting, and the seed validates what it reads.
//
// Run: npm run catalog:extract
import { readFileSync, writeFileSync } from "node:fs";
const src = readFileSync("src/lib/catalog.ts", "utf8");

// Pull each exported array literal and evaluate it as plain JS. The catalog is
// data only -- no JSX, no calls -- so stripping the type annotation is enough.
function grab(name) {
  const re = new RegExp(`export const ${name}[^=]*=\\s*(\\[[\\s\\S]*?\\n\\]);`, "m");
  const m = src.match(re);
  if (!m) throw new Error(`could not find ${name}`);
  return eval(m[1]);
}

const out = {
  models: grab("MODELS"),
  ratios: grab("RATIOS"),
  presets: grab("PRESETS"),
  plans: grab("PLANS"),
};
for (const [k, v] of Object.entries(out)) console.error(`${k}: ${v.length}`);
writeFileSync("prisma/seed/catalog.json", JSON.stringify(out, null, 2) + "\n");
