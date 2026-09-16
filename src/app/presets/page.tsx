"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { PRESETS, PRESET_FAMILIES, Preset, ratioById, modelById } from "@/lib/catalog";
import { frameUrl } from "@/lib/gen";
import { Asset } from "@/lib/store";
import Frame from "@/components/Frame";

function previewAsset(p: Preset): Asset {
  const model = modelById(p.mode === "motion" ? "reel-9" : "halide-2")!;
  const ratio = ratioById(p.mode === "motion" ? "16:9" : "4:5");
  return {
    id: `preview-${p.slug}`,
    kind: p.mode === "motion" ? "motion" : "image",
    url: frameUrl({
      prompt: p.previewPrompt,
      model,
      ratio,
      preset: p,
      seed: p.previewSeed,
      move: p.move ?? null,
    }),
    prompt: p.previewPrompt,
    composed: p.template.replace("{prompt}", p.previewPrompt),
    modelId: model.id,
    presetSlug: p.slug,
    ratioId: ratio.id,
    seed: p.previewSeed,
    move: p.move ?? null,
    createdAt: 0,
    author: "darkroom",
    published: true,
    likes: 0,
    cost: model.cost,
    seeded: true,
  };
}

export default function PresetsPage() {
  const [family, setFamily] = useState<string>("All");
  const [mode, setMode] = useState<"all" | "image" | "motion">("all");

  const list = useMemo(
    () =>
      PRESETS.filter(
        (p) =>
          (family === "All" || p.family === family) &&
          (mode === "all" || p.mode === mode),
      ),
    [family, mode],
  );

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-32 pt-10 sm:px-6">
      <header className="max-w-[62ch]">
        <h1 className="display text-[clamp(40px,6vw,68px)] leading-[0.92]">
          Presets do the
          <br />
          <span className="text-safelight">photography</span> for you.
        </h1>
        <p className="mt-5 text-[15px] leading-relaxed text-dim">
          A preset is a real prompt template plus, for motion, a camera move. Each
          one says what it does in plain language and shows you the same test
          prompt rendered through it, so you can compare like for like. Open any
          of them to see the exact template.
        </p>
      </header>

      <div className="sprocket my-8" />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        <div className="flex gap-1">
          {["All", ...PRESET_FAMILIES].map((f) => (
            <button
              key={f}
              onClick={() => setFamily(f)}
              className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
                family === f
                  ? "border-[#3a3a42] bg-[#1a1a1e] text-fg"
                  : "border-line text-faint hover:text-dim"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
        <span className="flex-1" />
        <div className="flex gap-1">
          {(["all", "image", "motion"] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`label px-2 py-1 ${mode === m ? "!text-fg" : "hover:!text-dim"}`}
            >
              {m === "all" ? "both" : m === "image" ? "stills" : "motion"}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {list.map((p, i) => (
          <PresetCard key={p.slug} preset={p} index={i} />
        ))}
      </div>
    </div>
  );
}

function PresetCard({ preset, index }: { preset: Preset; index: number }) {
  const [open, setOpen] = useState(false);
  const asset = useMemo(() => previewAsset(preset), [preset]);

  return (
    <div
      className="card overflow-hidden rise"
      style={{ animationDelay: `${Math.min(index, 9) * 50}ms` }}
    >
      <Frame asset={asset} rounded="" priority={index < 3} />
      <div className="p-3.5">
        <div className="flex items-baseline gap-2">
          <h3 className="text-[15px] font-medium">{preset.name}</h3>
          <span className="label">{preset.family}</span>
          <span className="flex-1" />
          {preset.move && <span className="label !text-safelight">{preset.move}</span>}
        </div>
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-dim">{preset.desc}</p>

        <div className="mt-3 flex items-center gap-2">
          <Link
            href={`/create?preset=${preset.slug}&model=${preset.mode === "motion" ? "reel-9" : "halide-2"}`}
            className="btn !h-8 !px-3 !text-[12px]"
          >
            Use it
          </Link>
          <Link
            href={`/create?preset=${preset.slug}&prompt=${encodeURIComponent(preset.previewPrompt)}&model=${preset.mode === "motion" ? "reel-9" : "halide-2"}&seed=${preset.previewSeed}`}
            className="btn btn-ghost !h-8 !px-2 !text-[12px]"
          >
            Remix this
          </Link>
          <span className="flex-1" />
          <button className="label hover:!text-fg" onClick={() => setOpen((v) => !v)}>
            {open ? "hide" : "template"}
          </button>
        </div>

        {open && (
          <p className="mono mt-3 rounded-[8px] border border-line bg-sunken p-2.5 text-[10.5px] leading-relaxed text-faint">
            {preset.template}
          </p>
        )}
      </div>
    </div>
  );
}
