"use client";

import { useEffect, useRef, useState } from "react";
import { Asset } from "@/lib/store";
import { MOVE_CLASS } from "@/lib/gen";
import { ratioById } from "@/lib/catalog";

/**
 * One generated frame.
 *
 * Motion assets are the generated keyframe played under the preset's camera
 * move. The move is a CSS transform, which is why it is smooth at any size and
 * costs nothing to scrub — and why the UI never calls it a video model.
 */
export default function Frame({
  asset,
  play = true,
  priority = false,
  className = "",
  rounded = "rounded-[10px]",
}: {
  asset: Asset;
  play?: boolean;
  priority?: boolean;
  className?: string;
  rounded?: string;
}) {
  const [state, setState] = useState<"loading" | "ok" | "err">("loading");
  const ratio = ratioById(asset.ratioId);
  const imgRef = useRef<HTMLImageElement>(null);

  useEffect(() => {
    const el = imgRef.current;
    if (el?.complete && el.naturalWidth > 0) setState("ok");
  }, [asset.url]);

  const moveClass =
    asset.kind === "motion" && asset.move && play ? MOVE_CLASS[asset.move] : "";

  return (
    <div
      className={`relative overflow-hidden bg-sunken ${rounded} ${
        asset.kind === "motion" ? "bloom scanline" : ""
      } ${className}`}
      style={{ aspectRatio: `${ratio.w} / ${ratio.h}` }}
    >
      {state === "loading" && (
        <div className="absolute inset-0 developing">
          <div className="absolute inset-0 grid place-items-center">
            <span className="label !text-[9px] opacity-60">developing</span>
          </div>
        </div>
      )}

      {state === "err" && (
        <div className="absolute inset-0 grid place-items-center bg-raised px-4 text-center">
          <div>
            <div className="label mb-1">frame lost</div>
            <button
              className="text-[11px] text-safelight underline underline-offset-2"
              onClick={() => {
                setState("loading");
                if (imgRef.current) {
                  const u = new URL(asset.url);
                  u.searchParams.set("r", String(Date.now()));
                  imgRef.current.src = u.toString();
                }
              }}
            >
              re-develop
            </button>
          </div>
        </div>
      )}

      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        ref={imgRef}
        src={asset.url}
        alt={asset.prompt}
        loading={priority ? "eager" : "lazy"}
        decoding="async"
        onLoad={() => setState("ok")}
        onError={() => setState("err")}
        className={`h-full w-full object-cover transition-opacity duration-700 ${
          state === "ok" ? "opacity-100" : "opacity-0"
        } ${moveClass}`}
        style={{ ["--dur" as string]: asset.kind === "motion" ? "6s" : undefined }}
      />

      {asset.kind === "motion" && state === "ok" && (
        <div className="pointer-events-none absolute left-2 top-2 z-[3] flex items-center gap-1.5 rounded-full bg-black/55 px-2 py-1 backdrop-blur-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-safelight pulse-dot" />
          <span className="label !text-[8px] !text-white/80">motion</span>
        </div>
      )}
    </div>
  );
}
