"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { type Asset, api } from "@/lib/api";
import { useDebouncedValue } from "@/lib/hooks/useDebouncedValue";
import { useInfiniteCursor } from "@/lib/hooks/useInfiniteCursor";
import { presetName, useStore } from "@/lib/store";
import Frame from "./Frame";

type Filter = "all" | "image" | "motion";

/**
 * The feed, served by the API and paged with a keyset cursor, so page 40 costs
 * what page 1 costs. Search is debounced and cancellable; the server enforces a
 * two-character minimum and its own rate limit regardless.
 */
export default function Wall({ limit = 24 }: { limit?: number }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery, 300);
  const search = query.trim().length >= 2 ? query.trim() : null;

  const fetchPage = useCallback(
    (cursor: string | null, signal: AbortSignal) =>
      api.wall({
        cursor,
        limit,
        mode: filter === "all" ? null : filter,
        q: search,
        signal,
      }),
    [filter, search, limit],
  );

  const { items, loading, loadMore, error } = useInfiniteCursor<Asset>(
    fetchPage,
    [filter, search, limit],
  );

  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadMore();
      },
      { rootMargin: "600px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {(["all", "image", "motion"] as Filter[]).map((f) => (
            <button
              key={f}
              data-testid={`wall-filter-${f}`}
              onClick={() => setFilter(f)}
              className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
                filter === f
                  ? "border-[#3a3a42] bg-[#1a1a1e] text-fg"
                  : "border-line text-faint hover:text-dim"
              }`}
            >
              {f === "all" ? "Everything" : f === "image" ? "Stills" : "Motion"}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        <input
          data-testid="wall-search"
          value={rawQuery}
          onChange={(e) => setRawQuery(e.target.value)}
          placeholder="Search prompts…"
          className="w-[220px] rounded-full border border-line bg-sunken px-3 py-1.5 text-[12px] text-fg outline-none placeholder:text-faint focus:border-[#3a3a42]"
        />
      </div>

      {error && (
        <p data-testid="wall-error" className="mb-4 text-[13px] text-red-400">
          {error.detail}
        </p>
      )}

      <div
        data-testid="wall-grid"
        className="[column-fill:_balance] columns-2 gap-3 sm:columns-3 lg:columns-4 xl:columns-5"
      >
        {items.map((a, i) => (
          <WallCard key={a.id} asset={a} index={i} />
        ))}
      </div>

      {!loading && items.length === 0 && (
        <p data-testid="wall-empty" className="py-16 text-center text-[13px] text-dim">
          {search ? `Nothing matches “${search}”.` : "Nothing on the wall yet."}
        </p>
      )}

      {loading && (
        <p data-testid="wall-loading" className="py-8 text-center label">
          developing…
        </p>
      )}

      <div ref={sentinel} aria-hidden className="h-px" />
    </>
  );
}

function WallCard({ asset, index }: { asset: Asset; index: number }) {
  const { catalog } = useStore();
  const [liked, setLiked] = useState(asset.likedByMe);
  const [count, setCount] = useState(asset.likeCount);
  const preset = presetName(catalog, asset.presetSlug);

  async function toggleLike() {
    // Optimistic: cheap, reversible, and the server is authoritative.
    const next = !liked;
    setLiked(next);
    setCount((c) => c + (next ? 1 : -1));
    try {
      await (next ? api.like(asset.id) : api.unlike(asset.id));
    } catch {
      setLiked(!next);
      setCount((c) => c + (next ? -1 : 1));
    }
  }

  const remix = new URLSearchParams({
    prompt: asset.prompt,
    model: asset.modelId,
    ratio: asset.ratioId,
    seed: String(asset.seed),
  });
  if (asset.presetSlug) remix.set("preset", asset.presetSlug);

  return (
    <div
      data-testid="wall-card"
      className="group relative mb-3 break-inside-avoid rise"
      style={{ animationDelay: `${Math.min(index, 14) * 40}ms` }}
    >
      <Link href={`/a/${asset.id}`} className="block">
        <Frame asset={asset} priority={index < 4} />
      </Link>

      {/* hover sheet — the prompt is the point */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[3] translate-y-1 rounded-b-[10px] bg-gradient-to-t from-black/92 via-black/70 to-transparent p-3 pt-10 opacity-0 transition-all duration-200 group-hover:translate-y-0 group-hover:opacity-100">
        <p
          data-testid="wall-card-prompt"
          className="line-clamp-2 text-[12px] leading-snug text-white/95"
        >
          {asset.prompt}
        </p>
        <div className="mt-1.5 flex items-center gap-2">
          <span className="label !text-[8px] !text-white/55">
            {preset ?? "no preset"}
          </span>
          <span className="flex-1" />
          <Link
            href={`/create?${remix.toString()}`}
            data-testid="wall-card-remix"
            className="pointer-events-auto rounded-full bg-safelight px-2.5 py-1 text-[10px] font-semibold text-[#1a0700]"
          >
            Remix
          </Link>
        </div>
      </div>

      <div className="mt-1.5 flex items-center gap-2 px-0.5">
        <span className="label truncate">@{asset.authorHandle}</span>
        <span className="flex-1" />
        <button
          onClick={toggleLike}
          data-testid="wall-card-like"
          className={`mono flex items-center gap-1 text-[10px] transition-colors ${
            liked ? "text-safelight" : "text-faint hover:text-dim"
          }`}
        >
          <svg width="11" height="11" viewBox="0 0 12 12" aria-hidden>
            <path
              d="M6 10.5S1 7.6 1 4.4A2.6 2.6 0 0 1 6 3.1 2.6 2.6 0 0 1 11 4.4c0 3.2-5 6.1-5 6.1Z"
              fill={liked ? "currentColor" : "none"}
              stroke="currentColor"
              strokeWidth="1.1"
            />
          </svg>
          {count.toLocaleString()}
        </button>
      </div>
    </div>
  );
}
