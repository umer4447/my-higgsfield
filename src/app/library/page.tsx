"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { type Asset, api } from "@/lib/api";
import { useDebouncedValue } from "@/lib/hooks/useDebouncedValue";
import { useInfiniteCursor } from "@/lib/hooks/useInfiniteCursor";
import { modelName, presetName, useStore } from "@/lib/store";
import Frame from "@/components/Frame";

/** Your own work. Paged from the server, searchable by prompt. */
export default function LibraryPage() {
  const { catalog, me } = useStore();
  const [mode, setMode] = useState<"all" | "image" | "motion">("all");
  const [onlyPublished, setOnlyPublished] = useState(false);
  const [rawQuery, setRawQuery] = useState("");
  const query = useDebouncedValue(rawQuery, 300);
  const search = query.trim().length >= 2 ? query.trim() : null;

  const fetchPage = useCallback(
    (cursor: string | null, signal: AbortSignal) =>
      api.library({
        cursor,
        limit: 24,
        mode: mode === "all" ? null : mode,
        published: onlyPublished ? true : null,
        q: search,
        signal,
      }),
    [mode, onlyPublished, search],
  );

  const { items, loading, reload } = useInfiniteCursor<Asset>(fetchPage, [
    mode,
    onlyPublished,
    search,
  ]);

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-32 pt-10 sm:px-6">
      <header className="mb-6 flex flex-wrap items-end gap-4 border-b border-line pb-5">
        <div>
          <h1 className="display text-[38px] leading-none">Contact sheet</h1>
          <p className="mt-1.5 text-[13.5px] text-dim">
            Everything you have developed
            {me ? ` · ${me.credits} credits left` : ""}. Publish a frame and it
            joins the wall with its prompt attached.
          </p>
        </div>
        <span className="flex-1" />
        <Link href="/create" className="btn btn-primary">
          Compose
        </Link>
      </header>

      <div className="mb-5 flex flex-wrap items-center gap-2">
        {(["all", "image", "motion"] as const).map((k) => (
          <button
            key={k}
            data-testid={`library-filter-${k}`}
            onClick={() => setMode(k)}
            className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
              mode === k
                ? "border-[#3a3a42] bg-[#1a1a1e] text-fg"
                : "border-line text-faint hover:text-dim"
            }`}
          >
            {k === "all" ? "Everything" : k === "image" ? "Stills" : "Motion"}
          </button>
        ))}
        <button
          onClick={() => setOnlyPublished((v) => !v)}
          className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
            onlyPublished
              ? "border-[#3a3a42] bg-[#1a1a1e] text-fg"
              : "border-line text-faint hover:text-dim"
          }`}
        >
          On the wall
        </button>
        <span className="flex-1" />
        <input
          data-testid="library-search"
          value={rawQuery}
          onChange={(e) => setRawQuery(e.target.value)}
          placeholder="Search your prompts…"
          className="w-[240px] rounded-full border border-line bg-sunken px-3 py-1.5 text-[12px] text-fg outline-none placeholder:text-faint focus:border-[#3a3a42]"
        />
      </div>

      {loading && items.length === 0 && (
        <p className="py-16 text-center label">loading…</p>
      )}

      {!loading && items.length === 0 && (
        <div data-testid="library-empty" className="py-20 text-center">
          <p className="text-[15px] text-dim">
            {search ? `Nothing matches “${search}”.` : "Nothing developed yet."}
          </p>
          {!search && (
            <Link href="/create" className="btn btn-primary mt-5">
              Develop your first frame
            </Link>
          )}
        </div>
      )}

      <div
        data-testid="library-grid"
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
      >
        {items.map((a, i) => (
          <LibraryCard
            key={a.id}
            asset={a}
            index={i}
            modelLabel={modelName(catalog, a.modelId)}
            presetLabel={presetName(catalog, a.presetSlug)}
            onChanged={reload}
          />
        ))}
      </div>
    </div>
  );
}

function LibraryCard({
  asset,
  index,
  modelLabel,
  presetLabel,
  onChanged,
}: {
  asset: Asset;
  index: number;
  modelLabel: string;
  presetLabel: string | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [published, setPublished] = useState(asset.published);

  async function togglePublish() {
    if (busy) return;
    setBusy(true);
    const next = !published;
    try {
      await api.publish(asset.id, next, asset.version);
      setPublished(next);
    } catch {
      /* the server is authoritative */
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (busy) return;
    setBusy(true);
    try {
      await api.remove(asset.id);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="library-card"
      className="rise"
      style={{ animationDelay: `${Math.min(index, 12) * 35}ms` }}
    >
      <Link href={`/a/${asset.id}`} className="block">
        <Frame asset={asset} priority={index < 5} />
      </Link>
      <p className="mt-1.5 line-clamp-2 text-[12px] leading-snug text-dim">
        {asset.prompt}
      </p>
      <p className="label mt-1 !text-[9px] truncate">
        {modelLabel}
        {presetLabel ? ` · ${presetLabel}` : ""} · seed {asset.seed}
      </p>
      <div className="mt-1.5 flex items-center gap-2">
        <button
          onClick={() => void togglePublish()}
          disabled={busy || asset.status !== "ready"}
          data-testid="library-publish"
          className={`label hover:!text-fg disabled:opacity-40 ${
            published ? "!text-safelight" : ""
          }`}
        >
          {published ? "on the wall" : "publish"}
        </button>
        <span className="flex-1" />
        <button
          onClick={() => void remove()}
          disabled={busy}
          className="label hover:!text-stop"
        >
          delete
        </button>
      </div>
    </div>
  );
}
