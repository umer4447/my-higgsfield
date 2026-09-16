import { SEED_ASSETS } from "@/lib/seed";

/**
 * What `npm run bake:wall` reads: the id and proxied URL of every seed frame,
 * so the baking script can pull each one down into /public without having to
 * re-implement prompt composition outside the app.
 */
export function GET() {
  return Response.json(
    SEED_ASSETS.map((a) => ({
      id: a.id,
      url: a.altUrl ?? a.url,
      prompt: a.prompt,
    })),
    { headers: { "cache-control": "no-store" } },
  );
}
