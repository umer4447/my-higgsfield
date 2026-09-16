"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Asset, useStore } from "@/lib/store";
import { SEED_ASSETS } from "@/lib/seed";
import { presetBySlug } from "@/lib/catalog";
import Frame from "./Frame";

type Filter = "all" | "image" | "motion";

export function useWallAssets(): Asset[] {
  const { state } = useStore();
  return useMemo(() => {
    const mine = state.assets.filter((a) => a.published);
    return [...mine, ...SEED_ASSETS];
  }, [state.assets]);
}

export default function Wall({ limit }: { limit?: number }) {
  const all = useWallAssets();
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<"hot" | "new">("hot");

  const items = useMemo(() => {
    let list = all.filter((a) => (filter === "all" ? true : a.kind === filter));
    list =
      sort === "hot"
        ? [...list].sort((a, b) => b.likes - a.likes)
        : [...list].sort((a, b) => b.createdAt - a.createdAt);
    return limit ? list.slice(0, limit) : list;
  }, [all, filter, sort, limit]);

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {(["all", "image", "motion"] as Filter[]).map((f) => (
            <button
              key={f}
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
        <div className="flex gap-1">
          {(["hot", "new"] as const).map((s) => (
            <button
              key={s}
              onClick={() => setSort(s)}
              className={`label px-2 py-1 ${sort === s ? "!text-fg" : "hover:!text-dim"}`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="[column-fill:_balance] columns-2 gap-3 sm:columns-3 lg:columns-4 xl:columns-5">
        {items.map((a, i) => (
          <WallCard key={a.id} asset={a} index={i} />
        ))}
      </div>
    </>
  );
}

function WallCard({ asset, index }: { asset: Asset; index: number }) {
  const { state, dispatch } = useStore();
  const liked = state.likedIds.includes(asset.id);
  const preset = asset.presetSlug ? presetBySlug(asset.presetSlug) : null;

  return (
    <div
      className="group relative mb-3 break-inside-avoid rise"
      style={{ animationDelay: `${Math.min(index, 14) * 40}ms` }}
    >
      <Link href={`/a/${asset.id}`} className="block">
        <Frame asset={asset} priority={index < 4} />
      </Link>

      {/* hover sheet — the prompt is the point */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[3] translate-y-1 rounded-b-[10px] bg-gradient-to-t from-black/92 via-black/70 to-transparent p-3 pt-10 opacity-0 transition-all duration-200 group-hover:translate-y-0 group-hover:opacity-100">
        <p className="line-clamp-2 text-[12px] leading-snug text-white/95">
          {asset.prompt}
        </p>
        <div className="mt-1.5 flex items-center gap-2">
          <span className="label !text-[8px] !text-white/55">
            {preset ? preset.name : "no preset"}
          </span>
          <span className="flex-1" />
          <Link
            href={`/create?prompt=${encodeURIComponent(asset.prompt)}&model=${asset.modelId}&preset=${asset.presetSlug ?? ""}&ratio=${asset.ratioId}&seed=${asset.seed}`}
            className="pointer-events-auto rounded-full bg-safelight px-2.5 py-1 text-[10px] font-semibold text-[#1a0700]"
          >
            Remix
          </Link>
        </div>
      </div>

      <div className="mt-1.5 flex items-center gap-2 px-0.5">
        <span className="label truncate">@{asset.author}</span>
        <span className="flex-1" />
        <button
          onClick={() => dispatch({ t: "like", id: asset.id })}
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
          {(asset.likes + (liked ? 1 : 0)).toLocaleString()}
        </button>
      </div>
    </div>
  );
}
