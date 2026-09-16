"use client";

import Link from "next/link";
import { use, useMemo } from "react";
import { notFound, useRouter } from "next/navigation";
import { useStore, modelName } from "@/lib/store";
import { SEED_ASSETS } from "@/lib/seed";
import { presetBySlug, modelById } from "@/lib/catalog";
import Frame from "@/components/Frame";
import ExportBar from "@/components/ExportBar";

export default function AssetPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const { state, dispatch } = useStore();

  const asset = useMemo(
    () => state.assets.find((a) => a.id === id) ?? SEED_ASSETS.find((a) => a.id === id),
    [state.assets, id],
  );

  if (state.ready && !asset) notFound();
  if (!asset) return null;

  const preset = asset.presetSlug ? presetBySlug(asset.presetSlug) : null;
  const model = modelById(asset.modelId);
  const liked = state.likedIds.includes(asset.id);
  const mine = !asset.seeded;

  const remixHref = `/create?prompt=${encodeURIComponent(asset.prompt)}&model=${asset.modelId}&preset=${asset.presetSlug ?? ""}&ratio=${asset.ratioId}&seed=${asset.seed}`;

  return (
    <div className="mx-auto max-w-[1400px] px-4 pb-32 pt-6 sm:px-6">
      <button onClick={() => router.back()} className="label mb-4 hover:!text-fg">
        ← back
      </button>

      <div className="grid gap-8 lg:grid-cols-[1.25fr_1fr]">
        <div>
          <Frame asset={asset} priority rounded="rounded-[14px]" />
          <ExportBar asset={asset} />
        </div>

        <div className="lg:pt-2">
          <div className="flex items-center gap-2">
            <span className="label">@{asset.author}</span>
            <span className="label">·</span>
            <span className="label">
              {new Date(asset.createdAt).toLocaleDateString(undefined, {
                day: "numeric",
                month: "short",
              })}
            </span>
            <span className="flex-1" />
            <button
              onClick={() => dispatch({ t: "like", id: asset.id })}
              className={`mono flex items-center gap-1.5 text-[12px] ${
                liked ? "text-safelight" : "text-faint hover:text-dim"
              }`}
            >
              <svg width="13" height="13" viewBox="0 0 12 12" aria-hidden>
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

          <h1 className="display mt-3 text-[clamp(28px,3.4vw,40px)] leading-[1.06]">
            {asset.prompt}
          </h1>

          <div className="mt-6 flex flex-wrap gap-2">
            <Link href={remixHref} className="btn btn-primary">
              Remix these settings
            </Link>
            {mine && (
              <button
                onClick={() =>
                  dispatch({
                    t: "asset:patch",
                    id: asset.id,
                    patch: { published: !asset.published },
                  })
                }
                className="btn"
              >
                {asset.published ? "Unpublish" : "Publish to the wall"}
              </button>
            )}
          </div>

          <div className="sprocket my-7" />

          <dl className="space-y-0">
            <Row k="Model" v={`${modelName(asset.modelId)} · ${model?.cost ?? "–"} cr`} />
            <Row
              k="Preset"
              v={
                preset ? (
                  <Link href="/presets" className="hover:text-fg">
                    {preset.name} <span className="text-faint">({preset.family})</span>
                  </Link>
                ) : (
                  "none"
                )
              }
            />
            {asset.move && <Row k="Camera" v={asset.move} />}
            <Row k="Frame" v={asset.ratioId} />
            <Row k="Seed" v={String(asset.seed)} />
          </dl>

          <div className="sprocket my-7" />

          <div className="label mb-2">the prompt that was sent</div>
          <p className="mono rounded-[10px] border border-line bg-sunken p-3.5 text-[11.5px] leading-relaxed text-dim">
            {asset.composed}
          </p>
          <p className="mt-3 text-[12px] leading-relaxed text-faint">
            This is the whole thing — your words plus the preset template. Nothing
            is held back. You can copy it, change one clause and see what moves.
          </p>

          {asset.kind === "motion" && (
            <p className="mt-6 rounded-[10px] border border-line bg-[rgba(255,90,31,0.05)] p-3.5 text-[12px] leading-relaxed text-dim">
              <span className="label !text-safelight">how motion works here</span>
              <br />
              The keyframe is genuinely generated by the model. The camera move is
              rendered in your browser from the preset, which is why it is instant
              and why you can export it. A frame-by-frame video model is the next
              thing to wire up, not something this is pretending to already be.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-4 border-b border-line-soft py-2.5 last:border-0">
      <dt className="label w-[74px] shrink-0">{k}</dt>
      <dd className="mono text-[12.5px] text-dim">{v}</dd>
    </div>
  );
}
