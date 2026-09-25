/**
 * The one typed client. Everything the UI knows about the server is here.
 *
 * It parses RFC 9457 problem+json into a typed error, surfaces Retry-After so a
 * 429 can render a real countdown instead of a generic failure, and carries the
 * request id so a browser error can be matched to a server log line.
 */

export type Mode = "image" | "motion";

export type Model = {
  id: string;
  name: string;
  vendor: string;
  mode: Mode;
  engine: string;
  creditCost: number;
  maxBatch: number;
  blurb: string;
  badge?: string | null;
};

export type Preset = {
  slug: string;
  name: string;
  family: "CAMERA" | "LIGHT" | "STOCK" | "WORLD";
  mode: Mode;
  description: string;
  template: string;
  move?: string | null;
  previewPrompt: string;
  previewSeed: number;
};

export type Ratio = {
  id: string;
  label: string;
  width: number;
  height: number;
  note: string;
};

export type Plan = {
  id: string;
  name: string;
  tagline: string;
  priceCents: number;
  monthlyCredits: number;
  maxBatch: number;
  maxConcurrentJobs: number;
  motionEnabled: boolean;
  perks: string[];
  featured: boolean;
};

export type Catalog = {
  models: Model[];
  presets: Preset[];
  ratios: Ratio[];
  plans: Plan[];
};

export type Me = {
  id: string;
  handle: string | null;
  isAnonymous: boolean;
  credits: number;
  planId: string;
  planName: string;
  maxConcurrentJobs: number;
  jobsInFlight: number;
  motionEnabled: boolean;
  createdAt: string;
};

export type Asset = {
  id: string;
  mode: Mode;
  status: "pending" | "running" | "ready" | "failed";
  prompt: string;
  composedPrompt: string;
  modelId: string;
  presetSlug: string | null;
  ratioId: string;
  seed: number;
  move: string | null;
  width: number;
  height: number;
  creditCost: number;
  authorHandle: string;
  published: boolean;
  likeCount: number;
  likedByMe: boolean;
  seeded: boolean;
  url: string | null;
  version: number;
  createdAt: string;
};

export type JobOutput = {
  id: string;
  status: "pending" | "running" | "ready" | "failed";
  seed: number;
  width: number;
  height: number;
  url: string | null;
  error: string | null;
};

export type Job = {
  id: string;
  status: "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled";
  mode: Mode;
  prompt: string;
  composedPrompt: string;
  modelId: string;
  presetSlug: string | null;
  ratioId: string;
  batch: number;
  move: string | null;
  creditsDebited: number;
  creditsRefunded: number;
  error: string | null;
  createdAt: string;
  finishedAt: string | null;
  outputs: JobOutput[];
};

export type Quote = {
  base: number;
  moveSurcharge: number;
  total: number;
  creditCostPerOutput: number;
  affordable: boolean;
  creditsAvailable: number;
};

export type LedgerRow = {
  id: string;
  reason: string;
  delta: number;
  balanceAfter: number;
  note: string | null;
  jobId: string | null;
  createdAt: string;
};

export type Page<T> = {
  data: T[];
  meta: { nextCursor: string | null; hasMore: boolean; limit: number };
};

/** A problem+json response, typed. */
export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail: string;
  readonly requestId: string | null;
  readonly retryAfter: number | null;
  readonly fields: { field: string; message: string }[];

  constructor(status: number, body: Record<string, unknown>, retryAfter: number | null) {
    const detail = typeof body.detail === "string" ? body.detail : "Something went wrong.";
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.title = typeof body.title === "string" ? body.title : "Error";
    this.detail = detail;
    this.requestId = typeof body.requestId === "string" ? body.requestId : null;
    this.retryAfter = retryAfter;
    this.fields = Array.isArray(body.errors)
      ? (body.errors as { field: string; message: string }[])
      : [];
  }

  /** True when waiting is the remedy rather than changing the request. */
  get isTransient() {
    return this.status === 429 || this.status === 503 || this.status === 502;
  }
}

type Options = RequestInit & { idempotencyKey?: string };

/** Query options every list endpoint accepts, plus cancellation. */
type Cancellable = { signal?: AbortSignal };

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { idempotencyKey, ...init } = options;
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);

  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });

  if (res.status === 204) return undefined as T;

  const isProblem = (res.headers.get("content-type") ?? "").includes("problem+json");
  if (!res.ok) {
    let body: Record<string, unknown> = {};
    if (isProblem || (res.headers.get("content-type") ?? "").includes("json")) {
      body = await res.json().catch(() => ({}));
    }
    const retry = res.headers.get("retry-after");
    throw new ApiError(res.status, body, retry ? Number(retry) : null);
  }
  return (await res.json()) as T;
}

/** A fresh key per submission intent, held across retries of that submission. */
export function newIdempotencyKey(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

function query(params: Record<string, string | number | boolean | null | undefined>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

export const api = {
  catalog: () => request<Catalog>("/v1/catalog"),

  signInAnonymously: () => request<Me>("/v1/auth/anonymous", { method: "POST" }),
  me: () => request<Me>("/v1/me"),
  claim: (handle: string) =>
    request<Me>("/v1/auth/claim", {
      method: "POST",
      body: JSON.stringify({ handle }),
    }),
  setPlan: (planId: string) =>
    request<Me>("/v1/me/plan", { method: "PATCH", body: JSON.stringify({ planId }) }),
  signOut: () => request<void>("/v1/auth/logout", { method: "POST" }),

  wall: ({ signal, ...p }: {
    cursor?: string | null;
    limit?: number;
    mode?: Mode | null;
    preset?: string | null;
    q?: string | null;
  } & Cancellable = {}) =>
    request<Page<Asset>>(`/v1/wall${query(p)}`, { signal }),

  library: ({ signal, ...p }: {
    cursor?: string | null;
    limit?: number;
    mode?: Mode | null;
    published?: boolean | null;
    q?: string | null;
  } & Cancellable = {}) =>
    request<Page<Asset>>(`/v1/library${query(p)}`, { signal }),

  asset: (id: string) => request<Asset>(`/v1/assets/${id}`),
  publish: (id: string, published: boolean, version?: number) =>
    request<Asset>(`/v1/assets/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ published }),
      headers: version ? { "If-Match": `"${version}"` } : undefined,
    }),
  remove: (id: string) => request<void>(`/v1/assets/${id}`, { method: "DELETE" }),
  like: (id: string) => request<void>(`/v1/assets/${id}/like`, { method: "PUT" }),
  unlike: (id: string) => request<void>(`/v1/assets/${id}/like`, { method: "DELETE" }),

  quote: (body: { modelId: string; batch: number; presetSlug?: string | null }) =>
    request<Quote>("/v1/jobs/quote", { method: "POST", body: JSON.stringify(body) }),

  submit: (
    body: {
      prompt: string;
      modelId: string;
      ratioId: string;
      presetSlug?: string | null;
      batch: number;
      seed?: number | null;
    },
    idempotencyKey: string,
  ) => request<Job>("/v1/jobs", { method: "POST", body: JSON.stringify(body), idempotencyKey }),

  jobs: (p: { cursor?: string | null; limit?: number; status?: string | null } = {}) =>
    request<Page<Job>>(`/v1/jobs${query(p)}`),
  job: (id: string) => request<Job>(`/v1/jobs/${id}`),
  cancel: (id: string) => request<Job>(`/v1/jobs/${id}/cancel`, { method: "POST" }),

  ledger: (p: { cursor?: string | null; limit?: number } = {}) =>
    request<Page<LedgerRow>>(`/v1/ledger${query(p)}`),
};

export type JobEvent =
  | { event: "ready"; data: { ok: true } }
  | { event: "job.updated"; data: { id: string; status: Job["status"] } }
  | { event: "output.ready"; data: { jobId: string; assetId: string } }
  | { event: "output.failed"; data: { jobId: string; assetId: string } }
  | { event: "credits.changed"; data: { jobId: string } };

/**
 * Subscribe to job transitions.
 *
 * One connection per tab replaces polling every in-flight job every second.
 * Mobile Safari and corporate proxies both drop long-lived connections, so the
 * caller is told when the stream fails and falls back to polling.
 */
export function subscribeToJobs(
  onEvent: (e: JobEvent) => void,
  onError: () => void,
): () => void {
  if (typeof EventSource === "undefined") return () => {};
  const source = new EventSource("/v1/jobs/stream", { withCredentials: true });
  const names: JobEvent["event"][] = [
    "ready",
    "job.updated",
    "output.ready",
    "output.failed",
    "credits.changed",
  ];
  for (const name of names) {
    source.addEventListener(name, (ev) => {
      try {
        onEvent({ event: name, data: JSON.parse((ev as MessageEvent).data) } as JobEvent);
      } catch {
        /* a malformed frame must not kill the stream */
      }
    });
  }
  source.onerror = () => {
    source.close();
    onError();
  };
  return () => source.close();
}
