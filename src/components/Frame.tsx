"use client";

import { useEffect, useRef, useState } from "react";
import { Asset } from "@/lib/store";
import { MOVE_CLASS } from "@/lib/gen";
import { ratioById } from "@/lib/catalog";
import { loadFrame, forget, PRIORITY } from "@/lib/loader";

/**
 * One generated frame.
 *
 * Nothing is requested until the tile is close to the viewport, and when it is,
 * it goes through the global queue rather than straight at the endpoint — two
 * dozen simultaneous diffusion requests get refused, not served.
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
  const [state, setState] = useState<"waiting" | "ok" | "err">("waiting");
  const [src, setSrc] = useState<string | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const deadRef = useRef(false);
  const ratio = ratioById(asset.ratioId);

  useEffect(() => {
    deadRef.current = false;
    return () => {
      deadRef.current = true;
    };
  }, []);

  useEffect(() => {
    setState("waiting");
    setSrc(null);
    let started = false;

    const start = () => {
      if (started) return;
      started = true;
      loadFrame(asset.url, {
        priority: priority ? PRIORITY.hero : PRIORITY.tile,
        cancelled: () => deadRef.current,
      })
        .then(() => {
          if (deadRef.current) return;
          setSrc(asset.url);
          setState("ok");
        })
        .catch(() => {
          if (!deadRef.current) setState("err");
        });
    };

    if (priority || typeof IntersectionObserver === "undefined") {
      start();
      return;
    }

    const el = boxRef.current;
    if (!el) {
      start();
      return;
    }
    // begin well before the tile is on screen so scrolling feels instant
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          start();
          io.disconnect();
        }
      },
      { rootMargin: "700px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [asset.url, priority]);

  function retry() {
    forget(asset.url);
    setState("waiting");
    loadFrame(asset.url, { priority: PRIORITY.job })
      .then(() => {
        if (deadRef.current) return;
        setSrc(asset.url);
        setState("ok");
      })
      .catch(() => {
        if (!deadRef.current) setState("err");
      });
  }

  const moveClass =
    asset.kind === "motion" && asset.move && play ? MOVE_CLASS[asset.move] : "";

  return (
    <div
      ref={boxRef}
      className={`relative overflow-hidden bg-sunken ${rounded} ${
        asset.kind === "motion" ? "bloom scanline" : ""
      } ${className}`}
      style={{ aspectRatio: `${ratio.w} / ${ratio.h}` }}
    >
      {state === "waiting" && (
        <div className="absolute inset-0 developing">
          <div className="absolute inset-0 grid place-items-center">
            <span className="label !text-[9px] opacity-60">developing</span>
          </div>
        </div>
      )}

      {state === "err" && (
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

      {src && (
        /* eslint-disable-next-line @next/next/no-img-element */
        <img
          src={src}
          alt={asset.prompt}
          decoding="async"
          /* the queue already pulled this into cache; if the cache missed, re-ask */
          onError={retry}
          className={`h-full w-full object-cover transition-opacity duration-700 ${
            state === "ok" ? "opacity-100" : "opacity-0"
          } ${moveClass}`}
          style={{ ["--dur" as string]: asset.kind === "motion" ? "6s" : undefined }}
        />
      )}

      {asset.kind === "motion" && state === "ok" && (
        <div className="pointer-events-none absolute left-2 top-2 z-[3] flex items-center gap-1.5 rounded-full bg-black/55 px-2 py-1 backdrop-blur-sm">
          <span className="h-1.5 w-1.5 rounded-full bg-safelight pulse-dot" />
          <span className="label !text-[8px] !text-white/80">motion</span>
        </div>
      )}
    </div>
  );
}
