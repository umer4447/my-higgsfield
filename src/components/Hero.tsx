"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type Asset, api } from "@/lib/api";
import { presetName, useStore } from "@/lib/store";
import Frame from "./Frame";

export default function Hero() {
  const { catalog } = useStore();
  const [featured, setFeatured] = useState<Asset[]>([]);
  const [i, setI] = useState(0);

  // The showcase is real published motion work, fetched from the feed rather
  // than a hardcoded list, so it reflects what is actually on the wall.
  useEffect(() => {
    let cancelled = false;
    api
      .wall({ mode: "motion", limit: 5 })
      .then((page) => {
        if (!cancelled) setFeatured(page.data);
      })
      .catch(() => {
        /* the hero copy stands on its own without the reel */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (featured.length < 2) return;
    const t = setInterval(() => setI((v) => (v + 1) % featured.length), 6500);
    return () => clearInterval(t);
  }, [featured.length]);

  const a = featured.length ? featured[i % featured.length] : null;
  const preset = a ? presetName(catalog, a.presetSlug) : null;

  return (
    <section className="relative overflow-hidden border-b border-line">
      {/* safelight wash */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            "radial-gradient(120% 90% at 78% 10%, rgba(255,90,31,0.13), transparent 58%), radial-gradient(90% 70% at 10% 100%, rgba(255,255,255,0.04), transparent 60%)",
        }}
      />

      <div className="relative mx-auto grid max-w-[1500px] items-center gap-10 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-[1.05fr_0.95fr] lg:py-24">
        <div>
          <div className="mb-5 flex items-center gap-2.5">
            <span className="h-1.5 w-1.5 rounded-full bg-safelight pulse-dot" />
            <span className="label !text-[10px]">
              Open studio · no account needed · 40 credits waiting
            </span>
          </div>

          <h1 className="display text-[clamp(52px,8.4vw,108px)] leading-[0.9] tracking-[-0.03em]">
            Say the shot.
            <br />
            <span className="text-safelight">Watch it develop.</span>
          </h1>

          <p className="mt-6 max-w-[50ch] text-[15px] leading-relaxed text-dim sm:text-[16px]">
            One composer. Stills and motion, every model and every preset in the
            same place — not fourteen apps pretending to be different products.
            The cost is on the button before you spend it, and every frame on the
            wall tells you exactly how it was made.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link href="/create" className="btn btn-primary !h-11 !px-6 !text-[14px]">
              Start composing
            </Link>
            <Link href="/presets" className="btn !h-11 !px-5 !text-[14px]">
              18 presets, described
            </Link>
          </div>

          <div className="mt-10 flex flex-wrap gap-x-8 gap-y-3 border-t border-line pt-5">
            {[
              ["2 cr", "a still"],
              ["18 cr", "a motion loop"],
              ["0", "sign-up steps"],
            ].map(([k, v]) => (
              <div key={v}>
                <div className="mono text-[17px] text-fg">{k}</div>
                <div className="label mt-0.5">{v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* featured frame */}
        {a && (
        <div className="relative">
          <div className="relative mx-auto max-w-[520px]">
            <div className="absolute -inset-3 rounded-[20px] border border-line-soft" aria-hidden />
            <Link href={`/a/${a.id}`} className="relative block">
              <Frame asset={a} priority rounded="rounded-[14px]" />
            </Link>
            <div className="mt-3 flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] text-fg">{a.prompt}</p>
                <p className="label mt-1">
                  {preset ?? "no preset"} · {a.ratioId} · seed {a.seed}
                </p>
              </div>
              <Link
                href={`/create?prompt=${encodeURIComponent(a.prompt)}&model=${a.modelId}&preset=${a.presetSlug ?? ""}&ratio=${a.ratioId}&seed=${a.seed}`}
                className="btn !h-8 shrink-0 !px-3 !text-[12px]"
              >
                Remix
              </Link>
            </div>
            <div className="mt-3 flex gap-1.5">
              {featured.map((f, n) => (
                <button
                  key={f.id}
                  onClick={() => setI(n)}
                  aria-label={`Featured ${n + 1}`}
                  className={`h-[3px] flex-1 rounded-full transition-colors ${
                    n === i ? "bg-safelight" : "bg-line"
                  }`}
                />
              ))}
            </div>
          </div>
        </div>
        )}
      </div>
    </section>
  );
}
