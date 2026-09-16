/**
 * Frame loader — a global queue in front of the generation endpoint.
 *
 * The wall has two dozen tiles. Firing two dozen diffusion requests at once
 * gets most of them refused, which is what "frame lost" was: not a broken
 * image, a stampede. So every frame in the app goes through here.
 *
 *   - at most MAX requests in flight, everywhere in the app, at once
 *   - a job you started outranks a tile you happen to be scrolling past
 *   - failures retry with backoff before anyone is told anything went wrong
 *
 * The hard pacing lives server-side in /api/frame, which is the only thing that
 * talks to the generator; this queue is about not asking the browser for forty
 * things at once.
 *
 * Tiles only enqueue when they come near the viewport (see Frame), so opening
 * the wall queues the screenful you can see, not the whole page.
 */

const MAX_IN_FLIGHT = 4;
const MAX_ATTEMPTS = 3;
const BASE_BACKOFF = 2000;

/** higher runs first */
export const PRIORITY = {
  job: 100, // something the user just paid credits for
  hero: 50, // above the fold
  tile: 10, // everything else
} as const;

type Task = {
  url: string;
  priority: number;
  attempts: number;
  resolve: () => void;
  reject: (e: Error) => void;
  cancelled: () => boolean;
};

const queue: Task[] = [];
const done = new Map<string, "ok" | "failed">();
const inFlightUrls = new Map<string, Task[]>();
let running = 0;

function pump() {
  while (running < MAX_IN_FLIGHT && queue.length) {
    queue.sort((a, b) => b.priority - a.priority || a.attempts - b.attempts);
    const task = queue.shift()!;
    if (task.cancelled()) continue;
    run(task);
  }
}

function run(task: Task) {
  running += 1;
  const img = new Image();
  let settled = false;

  const finish = (ok: boolean) => {
    if (settled) return;
    settled = true;
    running -= 1;
    img.onload = img.onerror = null;

    if (ok) {
      done.set(task.url, "ok");
      resolveAll(task.url);
      pump();
      return;
    }

    task.attempts += 1;
    if (task.attempts < MAX_ATTEMPTS && !task.cancelled()) {
      // jittered backoff: a stampede that retries in lockstep is still a stampede
      const wait =
        BASE_BACKOFF * 2 ** (task.attempts - 1) + Math.random() * 900;
      setTimeout(() => {
        queue.push(task);
        pump();
      }, wait);
    } else {
      done.set(task.url, "failed");
      rejectAll(task.url, new Error("frame did not come back"));
    }
    pump();
  };

  img.onload = () => finish(true);
  img.onerror = () => finish(false);
  // a request still open after 90s is not going to land
  setTimeout(() => finish(img.complete && img.naturalWidth > 0), 90_000);
  img.src = task.url;
}

function resolveAll(url: string) {
  const waiting = inFlightUrls.get(url) ?? [];
  inFlightUrls.delete(url);
  waiting.forEach((t) => t.resolve());
}

function rejectAll(url: string, e: Error) {
  const waiting = inFlightUrls.get(url) ?? [];
  inFlightUrls.delete(url);
  waiting.forEach((t) => t.reject(e));
}

/**
 * Resolves once the frame is in the browser cache, so the <img> that follows
 * paints instantly. Rejects only after every retry is spent.
 */
export function loadFrame(
  url: string,
  opts: { priority?: number; cancelled?: () => boolean } = {},
): Promise<void> {
  const state = done.get(url);
  if (state === "ok") return Promise.resolve();
  if (state === "failed") done.delete(url); // an explicit re-ask gets a clean slate

  return new Promise<void>((resolve, reject) => {
    const task: Task = {
      url,
      priority: opts.priority ?? PRIORITY.tile,
      attempts: 0,
      resolve,
      reject,
      cancelled: opts.cancelled ?? (() => false),
    };

    // several tiles can want the same url (the hero and its wall tile, say)
    const waiting = inFlightUrls.get(url);
    if (waiting) {
      waiting.push(task);
      return;
    }
    inFlightUrls.set(url, [task]);
    queue.push(task);
    pump();
  });
}

/** Throw away what we know about a url so it is fetched again from scratch. */
export function forget(url: string) {
  done.delete(url);
}

export function queueDepth() {
  return { running, waiting: queue.length };
}
