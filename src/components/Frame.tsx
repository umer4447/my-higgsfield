"use client";

import { useState } from "react";
import type { Asset } from "@/lib/api";
import { MOVE_CLASS } from "@/lib/moves";

/**
 * One generated frame.
 *
 * Much smaller than it was: the client used to run a priority queue in front of
 * the generator because two dozen simultaneous diffusion requests get refused.
 * The server paces now -- a token bucket and a concurrency throttle shared
 * across instances -- so this is a plain image with native lazy loading.
 *
 * `asset.url` is always one of ours (/v1/frames/:id), never an upstream or
 * storage location, and it is null until the frame is READY.
 */
export default function Frame({
  asset,
  play = true,
  priority = false,
  className = "",
  rounded = "rounded-[10px]",
}: {
  asset: Pick<Asset, "id" | "mode" | "status" | "prompt" | "url" | "move" | "width" | "height">;
  play?: boolean;
  priority?: boolean;
  className?: string;
  rounded?: string;
}) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const pending = asset.status === "pending" || asset.status === "running";
  const src = asset.url ? `${asset.url}${attempt ? `?retry=${attempt}` : ""}` : null;
  const moveClass = asset.mode === "motion" && asset.move && play
    ? MOVE_CLASS[asset.move] ?? ""
    : "";

  function retry() {
    setFailed(false);
    setLoaded(false);
    setAttempt((n) => n + 1);
  }

  return (
    <div
      data-testid="frame"
      data-frame-status={asset.status}
      className={`relative overflow-hidden bg-sunken ${rounded} ${
        asset.mode === "motion" ? "bloom scanline" : ""
      } ${className}`}
      style={{ aspectRatio: `${asset.width} / ${asset.height}` }}
    >
      {(pending || (!loaded && !failed && src)) && (
        <div className="absolute inset-0 developing">
          <div className="absolute inset-0 grid place-items-center">
            <span className="label !text-[9px] opacity-60">
              {pending ? "developing" : "loading"}
            </span>
          </div>
        </div>
      )}

      {(failed || asset.status === "failed") && (
        <div className="absolute inset-0 grid place-items-center bg-raised px-4 text-center">
          <div>
            <div className="label mb-1.5">frame lost</div>
            <button
              className="text-[11px] text-safelight underline underline-offset-2"
              onClick={retry}
            >
              re-develop
            </button>
          </div>
        </div>
      )}

      {src && !failed && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={src}
          alt={asset.prompt}
          loading={priority ? "eager" : "lazy"}
          decoding="async"
          fetchPriority={priority ? "high" : "auto"}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          className={`h-full w-full object-cover transition-opacity duration-700 ${
            loaded ? "opacity-100" : "opacity-0"
          } ${moveClass}`}
          style={{ ["--dur" as string]: asset.mode === "motion" ? "6s" : undefined }}
        />
      )}

      {asset.mode === "motion" && loaded && (
        <div className="pointer-events-none absolute left-2 top-2 z-[3] flex items-center gap-1.5 rounded-full bg-black/55 px-2 py-1 backdrop-blur-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-safelight pulse-dot" />
          <span className="label !text-[8px] !text-white/80">motion</span>
        </div>
      )}
    </div>
  );
}
