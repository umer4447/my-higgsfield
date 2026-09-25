"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, type Asset, api } from "@/lib/api";
import { MOVE_LABEL } from "@/lib/moves";
import { modelName, presetName, useStore } from "@/lib/store";
import Frame from "@/components/Frame";
import ExportBar from "@/components/ExportBar";

/** One frame, with everything needed to remake it. */
export default function AssetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { catalog, me } = useStore();

  const [asset, setAsset] = useState<Asset | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /* State is written from the promise callbacks, never in the effect body:
     this is a subscription to an external system, which is what effects are
     for. The cancelled flag stops a slow response repainting a stale frame. */
  const [reloadAt, setReloadAt] = useState(0);
  const reload = useCallback(() => setReloadAt((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    api
      .asset(id)
      .then((next) => {
        if (!cancelled) {
          setAsset(next);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.detail : "Could not load that frame.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id, reloadAt]);

  if (error) {
    return (
      <div className="mx-auto max-w-[900px] px-6 py-24 text-center">
        <h1 className="display text-[34px]">Not here.</h1>
        <p className="mt-3 text-[14px] text-dim">{error}</p>
        <Link href="/" className="btn mt-6">
          Back to the wall
        </Link>
      </div>
    );
  }

  if (!asset) {
    return (
      <div className="mx-auto max-w-[900px] px-6 py-24">
        <p className="label">loading…</p>
      </div>
    );
  }

  const preset = presetName(catalog, asset.presetSlug);
  const mine = me?.id !== undefined && !asset.seeded;

  const remix = new URLSearchParams({
    prompt: asset.prompt,
    model: asset.modelId,
    ratio: asset.ratioId,
    seed: String(asset.seed),
  });
  if (asset.presetSlug) remix.set("preset", asset.presetSlug);

  async function toggleLike() {
    if (!asset) return;
    const next = !asset.likedByMe;
    setAsset({
      ...asset,
      likedByMe: next,
      likeCount: asset.likeCount + (next ? 1 : -1),
    });
    try {
      await (next ? api.like(asset.id) : api.unlike(asset.id));
    } catch {
      reload();
    }
  }

  async function togglePublish() {
    if (!asset || busy) return;
    setBusy(true);
    try {
      setAsset(await api.publish(asset.id, !asset.published, asset.version));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not publish.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!asset || busy) return;
    setBusy(true);
    try {
      await api.remove(asset.id);
      router.push("/library");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto grid max-w-[1400px] gap-8 px-4 pb-32 pt-8 sm:px-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div>
        <Frame asset={asset} priority rounded="rounded-[14px]" />
        <ExportBar asset={asset} />
      </div>

      <div>
        <div className="flex items-center gap-2">
          <span className="label">@{asset.authorHandle}</span>
          <span className="flex-1" />
          <button
            onClick={() => void toggleLike()}
            data-testid="asset-like"
            className={`mono text-[11px] ${
              asset.likedByMe ? "text-safelight" : "text-faint hover:text-dim"
            }`}
          >
            ♥ {asset.likeCount.toLocaleString()}
          </button>
        </div>

        <h1 data-testid="asset-prompt" className="display mt-3 text-[30px] leading-[1.1]">
          {asset.prompt}
        </h1>

        <dl className="mt-6 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-line pt-5">
          {[
            ["Model", modelName(catalog, asset.modelId)],
            ["Preset", preset ?? "none"],
            ["Frame", asset.ratioId],
            ["Seed", String(asset.seed)],
            ["Cost", `${asset.creditCost} cr`],
            ...(asset.move ? [["Move", MOVE_LABEL[asset.move] ?? asset.move]] : []),
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="label">{k}</dt>
              <dd className="mono mt-0.5 text-[13px] text-fg">{v}</dd>
            </div>
          ))}
        </dl>

        <div className="mt-6 border-t border-line pt-5">
          <div className="label mb-2">the prompt that was actually sent</div>
          <p
            data-testid="asset-composed"
            className="mono rounded-[8px] border border-line bg-sunken p-3 text-[11.5px] leading-relaxed text-dim"
          >
            {asset.composedPrompt}
          </p>
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <Link
            href={`/create?${remix.toString()}`}
            data-testid="asset-remix"
            className="btn btn-primary"
          >
            Remix
          </Link>
          {mine && (
            <>
              <button
                onClick={() => void togglePublish()}
                disabled={busy || asset.status !== "ready"}
                className="btn"
                data-testid="asset-publish"
              >
                {asset.published ? "Remove from wall" : "Publish to wall"}
              </button>
              <button onClick={() => void remove()} disabled={busy} className="btn">
                Delete
              </button>
            </>
          )}
          <Link href="/" className="btn btn-ghost">
            Back to the wall
          </Link>
        </div>

        {asset.mode === "motion" && (
          <p className="mt-6 rounded-[8px] border border-line bg-sunken p-3 text-[12px] leading-relaxed text-dim">
            This is a generated keyframe played under the camera move the preset
            asks for. The frame is generated; the move is rendered in your
            browser — which is also why the export is a real file.
          </p>
        )}
      </div>
    </div>
  );
}
