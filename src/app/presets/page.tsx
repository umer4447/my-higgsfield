"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { Preset } from "@/lib/api";
import { useStore } from "@/lib/store";

const FAMILIES = ["CAMERA", "LIGHT", "STOCK", "WORLD"] as const;
const FAMILY_LABEL: Record<string, string> = {
  CAMERA: "Camera",
  LIGHT: "Light",
  STOCK: "Stock",
  WORLD: "World",
};

/**
 * Every preset, in full.
 *
 * The template is readable rather than hidden, which is the point: a preset you
 * cannot read is a black box you cannot learn from.
 */
export default function PresetsPage() {
  const { catalog, ready } = useStore();
  const [family, setFamily] = useState<string>("All");
  const [mode, setMode] = useState<"all" | "image" | "motion">("all");

  const presets = useMemo(() => {
    const all = catalog?.presets ?? [];
    return all.filter(
      (p) =>
        (family === "All" || p.family === family) &&
        (mode === "all" || p.mode === mode),
    );
  }, [catalog, family, mode]);

  return (
    <div className="mx-auto max-w-[1400px] px-4 pb-32 pt-10 sm:px-6">
      <header className="max-w-[62ch]">
        <h1 className="display text-[clamp(38px,5.5vw,62px)] leading-[0.95]">
          Presets, with
          <br />
          nothing hidden.
        </h1>
        <p className="mt-5 text-[15px] leading-relaxed text-dim">
          Each one is a prompt template. You can read every word of it, which is
          the difference between a preset you can learn from and a button that
          does something to your image.
        </p>
      </header>

      <div className="mt-8 flex flex-wrap items-center gap-2 border-b border-line pb-5">
        {["All", ...FAMILIES].map((f) => (
          <button
            key={f}
            data-testid={`preset-family-${f}`}
            onClick={() => setFamily(f)}
            className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
              family === f
                ? "border-[#3a3a42] bg-[#1a1a1e] text-fg"
                : "border-line text-faint hover:text-dim"
            }`}
          >
            {f === "All" ? "All families" : FAMILY_LABEL[f]}
          </button>
        ))}
        <span className="flex-1" />
        {(["all", "image", "motion"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`label px-2 py-1 ${mode === m ? "!text-fg" : "hover:!text-dim"}`}
          >
            {m}
          </button>
        ))}
      </div>

      {!ready && <p className="py-16 text-center label">loading…</p>}

      <div
        data-testid="preset-grid"
        className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      >
        {presets.map((p) => (
          <PresetCard key={p.slug} preset={p} />
        ))}
      </div>

      {ready && presets.length === 0 && (
        <p className="py-16 text-center text-[14px] text-dim">
          No presets in that combination.
        </p>
      )}
    </div>
  );
}

function PresetCard({ preset }: { preset: Preset }) {
  const [open, setOpen] = useState(false);

  const remix = new URLSearchParams({
    prompt: preset.previewPrompt,
    preset: preset.slug,
    seed: String(preset.previewSeed),
  });

  return (
    <article
      data-testid="preset-card"
      className="flex flex-col rounded-[12px] border border-line bg-sunken p-4"
    >
      <div className="flex items-baseline gap-2">
        <h2 className="text-[15px] font-medium text-fg">{preset.name}</h2>
        <span className="label">{FAMILY_LABEL[preset.family]}</span>
        <span className="flex-1" />
        {preset.move && <span className="label !text-safelight">motion</span>}
      </div>

      <p className="mt-2 text-[13px] leading-relaxed text-dim">{preset.description}</p>

      <button
        onClick={() => setOpen((v) => !v)}
        className="label mt-3 text-left hover:!text-fg"
      >
        {open ? "▾" : "▸"} the template, in full
      </button>
      {open && (
        <p
          data-testid="preset-template"
          className="mono mt-2 rounded-[8px] border border-line bg-bg p-2.5 text-[11px] leading-relaxed text-dim"
        >
          {preset.template}
        </p>
      )}

      <div className="mt-auto flex items-center gap-2 pt-4">
        <span className="label truncate">“{preset.previewPrompt}”</span>
        <span className="flex-1" />
        <Link href={`/create?${remix.toString()}`} className="btn !h-8 !px-3 !text-[12px]">
          Try it
        </Link>
      </div>
    </article>
  );
}
