import { NextRequest } from "next/server";

/**
 * Frame proxy.
 *
 * The upstream generator rate-limits per IP and answers 503 once you cross it.
 * Going at it straight from the browser means every visitor burns the same
 * allowance and most of the wall fails — which is exactly what happened.
 *
 * So frames are fetched here instead:
 *
 *   - one upstream request per unique URL, ever, because the response carries
 *     immutable cache headers and the CDN keeps it. A second visitor asking for
 *     the same frame never reaches the generator at all.
 *   - requests are paced and serialised per instance, so we stay under the limit
 *     rather than discovering it.
 *   - a 503 is retried here, where waiting is free, instead of being handed to
 *     the browser as a dead tile.
 *
 * Generation is genuinely slow, so this handler can run for a while; that is
 * what maxDuration is for.
 */

export const runtime = "nodejs";
export const maxDuration = 60;

const UPSTREAM = "https://image.pollinations.ai/prompt/";

/** minimum gap between two upstream requests from this instance */
const MIN_GAP_MS = 1500;
let chain: Promise<unknown> = Promise.resolve();
let lastStart = 0;

function serialise<T>(fn: () => Promise<T>): Promise<T> {
  const next = chain.then(async () => {
    const wait = Math.max(0, lastStart + MIN_GAP_MS - Date.now());
    if (wait) await new Promise((r) => setTimeout(r, wait));
    lastStart = Date.now();
    return fn();
  });
  // keep the chain alive even when a link rejects
  chain = next.catch(() => {});
  return next;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const prompt = sp.get("p");
  if (!prompt) return new Response("missing prompt", { status: 400 });

  const qs = new URLSearchParams({
    width: sp.get("w") ?? "832",
    height: sp.get("h") ?? "832",
    seed: sp.get("seed") ?? "1",
    model: sp.get("model") ?? "flux",
    nologo: "true",
    referrer: "darkroom",
  });
  const target = `${UPSTREAM}${encodeURIComponent(prompt)}?${qs}`;

  const ATTEMPTS = 3;
  let lastStatus = 0;

  for (let attempt = 0; attempt < ATTEMPTS; attempt++) {
    try {
      const res = await serialise(() =>
        fetch(target, {
          headers: { accept: "image/*" },
          signal: AbortSignal.timeout(45_000),
        }),
      );

      if (res.ok) {
        const body = await res.arrayBuffer();
        return new Response(body, {
          status: 200,
          headers: {
            "content-type": res.headers.get("content-type") ?? "image/jpeg",
            // deterministic input, immutable output: cache it hard, everywhere
            "cache-control":
              "public, max-age=86400, s-maxage=31536000, stale-while-revalidate=86400, immutable",
          },
        });
      }

      lastStatus = res.status;
      // 503 here means "slow down", so slowing down is the whole remedy
      if (res.status === 503 || res.status === 429) {
        await sleep(2500 * (attempt + 1) + Math.random() * 1500);
        continue;
      }
      break;
    } catch {
      lastStatus = 504;
      await sleep(1500 * (attempt + 1));
    }
  }

  return new Response(`upstream ${lastStatus || "unavailable"}`, {
    status: 502,
    headers: { "cache-control": "no-store" },
  });
}
