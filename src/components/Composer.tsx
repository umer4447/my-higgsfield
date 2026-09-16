"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  MODELS,
  PRESETS,
  PRESET_FAMILIES,
  RATIOS,
  Mode,
  modelById,
  presetBySlug,
  ratioById,
} from "@/lib/catalog";
import { composePrompt, priceJob } from "@/lib/gen";
import { useStore } from "@/lib/store";
import { useSubmit } from "@/lib/jobs";
import Frame from "./Frame";

const IDEAS = [
  "a fishmonger hosing down the floor at closing time",
  "a satellite dish farm in the desert at dusk",
  "a ballet dancer taping her feet backstage",
  "an overgrown petrol station reclaimed by ivy",
  "two brothers arguing over a car engine",
  "a hotel corridor with one door open",
];

export default function Composer() {
  const router = useRouter();
  const params = useSearchParams();
  const { state, dispatch } = useStore();
  const submit = useSubmit();
  const areaRef = useRef<HTMLTextAreaElement>(null);

  const [mode, setMode] = useState<Mode>("image");
  const [prompt, setPrompt] = useState("");
  const [modelId, setModelId] = useState("halide-2");
  const [presetSlug, setPresetSlug] = useState<string | null>(null);
  const [ratioId, setRatioId] = useState("4:5");
  const [batch, setBatch] = useState(2);
  const [lockSeed, setLockSeed] = useState<number | null>(null);
  const [family, setFamily] = useState<string>("All");
  const [err, setErr] = useState<string | null>(null);
  const [lastJobId, setLastJobId] = useState<string | null>(null);
  const [showFull, setShowFull] = useState(false);

  /* ---- remix: hydrate from the query string ---- */
  useEffect(() => {
    const p = params.get("prompt");
    const m = params.get("model");
    const pr = params.get("preset");
    const r = params.get("ratio");
    const s = params.get("seed");
    if (p) setPrompt(p);
    if (m && modelById(m)) {
      setModelId(m);
      setMode(modelById(m)!.mode);
    }
    if (pr && presetBySlug(pr)) setPresetSlug(pr);
    if (r && RATIOS.some((x) => x.id === r)) setRatioId(r);
    if (s && !Number.isNaN(Number(s))) setLockSeed(Number(s));
    if (p) setTimeout(() => areaRef.current?.focus(), 60);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const models = useMemo(() => MODELS.filter((m) => m.mode === mode), [mode]);
  const model = modelById(modelId) ?? models[0];
  const preset = presetSlug ? presetBySlug(presetSlug) ?? null : null;
  const ratio = ratioById(ratioId);

  /* keep model and mode consistent */
  useEffect(() => {
    if (model.mode !== mode) setModelId(models[0].id);
    if (batch > model.maxBatch) setBatch(model.maxBatch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, modelId]);

  /* a motion job needs a preset that carries a camera move */
  useEffect(() => {
    if (mode === "motion" && preset && !preset.move) setPresetSlug(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const visiblePresets = useMemo(
    () =>
      PRESETS.filter(
        (p) =>
          (mode === "image" ? true : !!p.move) &&
          (family === "All" || p.family === family),
      ),
    [mode, family],
  );

  const price = priceJob(model, batch, preset);
  const affordable = state.credits >= price.total;
  const composed = composePrompt(prompt, preset);

  const lastJob = state.jobs.find((j) => j.id === lastJobId);
  const lastAssets = lastJob
    ? state.assets.filter((a) => lastJob.assetIds.includes(a.id))
    : [];

  function go() {
    setErr(null);
    const res = submit({ prompt, model, ratio, preset, batch, seed: lockSeed });
    if (!res.ok) {
      setErr(res.reason ?? "Something went wrong.");
      return;
    }
    setLastJobId(res.jobId!);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        go();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <div className="mx-auto grid max-w-[1500px] gap-6 px-4 pb-32 pt-6 sm:px-6 lg:grid-cols-[404px_1fr]">
      {/* ------------------------------ controls ------------------------------ */}
      <div className="lg:sticky lg:top-[77px] lg:self-start">
        <div className="card overflow-hidden">
          {/* mode */}
          <div className="grid grid-cols-2 border-b border-line-soft">
            {(["image", "motion"] as Mode[]).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={`relative py-3 text-[13px] transition-colors ${
                  mode === m ? "text-fg" : "text-faint hover:text-dim"
                }`}
              >
                {m === "image" ? "Still" : "Motion"}
                {mode === m && (
                  <span className="absolute inset-x-8 bottom-0 h-px bg-safelight" />
                )}
              </button>
            ))}
          </div>

          {/* prompt */}
          <div className="p-3">
            <textarea
              ref={areaRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              placeholder="Describe the shot. Plain language works better than keyword soup."
              className="field w-full resize-none p-3 text-[14px] leading-relaxed placeholder:text-faint focus:outline-none"
            />
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <button
                className="label hover:!text-fg"
                onClick={() =>
                  setPrompt(IDEAS[Math.floor(Math.random() * IDEAS.length)])
                }
              >
                ↻ surprise me
              </button>
              <span className="flex-1" />
              <span className="label">{prompt.trim().length} ch</span>
            </div>
          </div>

          <div className="sprocket mx-3" />

          {/* model */}
          <div className="p-3">
            <div className="label mb-2">model</div>
            <div className="space-y-1.5">
              {models.map((m) => (
                <button
                  key={m.id}
                  onClick={() => setModelId(m.id)}
                  className={`flex w-full items-start gap-3 rounded-[8px] border p-2.5 text-left transition-colors ${
                    modelId === m.id
                      ? "border-[#3a3a42] bg-[#1a1a1e]"
                      : "border-transparent hover:bg-[#151518]"
                  }`}
                >
                  <span
                    className={`mt-[3px] h-2.5 w-2.5 shrink-0 rounded-full border ${
                      modelId === m.id
                        ? "border-safelight bg-safelight"
                        : "border-[#3a3a42]"
                    }`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="text-[13px] font-medium">{m.name}</span>
                      {m.badge && (
                        <span className="label !text-[8px] rounded-full border border-line px-1.5 py-[1px]">
                          {m.badge}
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-[11.5px] leading-snug text-faint">
                      {m.blurb}
                    </span>
                  </span>
                  <span className="mono shrink-0 text-[11px] text-dim">{m.cost}cr</span>
                </button>
              ))}
            </div>
          </div>

          <div className="sprocket mx-3" />

          {/* ratio + batch */}
          <div className="grid grid-cols-2 gap-3 p-3">
            <div>
              <div className="label mb-2">frame</div>
              <div className="flex flex-wrap gap-1">
                {RATIOS.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => setRatioId(r.id)}
                    title={r.note}
                    className={`mono rounded-[6px] border px-2 py-1 text-[11px] transition-colors ${
                      ratioId === r.id
                        ? "border-safelight text-safelight"
                        : "border-line text-dim hover:text-fg"
                    }`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <div className="label mb-2">outputs</div>
              <div className="flex gap-1">
                {Array.from({ length: model.maxBatch }, (_, i) => i + 1).map((n) => (
                  <button
                    key={n}
                    onClick={() => setBatch(n)}
                    className={`mono h-[26px] w-[26px] rounded-[6px] border text-[11px] transition-colors ${
                      batch === n
                        ? "border-safelight text-safelight"
                        : "border-line text-dim hover:text-fg"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
              {lockSeed != null && (
                <button
                  onClick={() => setLockSeed(null)}
                  className="label mt-2 hover:!text-fg"
                  title="Unlock the seed to get variation"
                >
                  ⚿ seed {lockSeed} — unlock
                </button>
              )}
            </div>
          </div>

          <div className="sprocket mx-3" />

          {/* presets */}
          <div className="p-3">
            <div className="mb-2 flex items-center gap-2">
              <span className="label">preset</span>
              <span className="flex-1" />
              {preset && (
                <button className="label hover:!text-fg" onClick={() => setPresetSlug(null)}>
                  clear
                </button>
              )}
            </div>
            <div className="mb-2 flex gap-1 overflow-x-auto pb-1">
              {["All", ...PRESET_FAMILIES].map((f) => (
                <button
                  key={f}
                  onClick={() => setFamily(f)}
                  className={`shrink-0 rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                    family === f
                      ? "border-[#3a3a42] bg-[#1a1a1e] text-fg"
                      : "border-line text-faint hover:text-dim"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            <div className="grid max-h-[230px] grid-cols-2 gap-1.5 overflow-y-auto pr-1">
              {visiblePresets.map((p) => (
                <button
                  key={p.slug}
                  onClick={() => setPresetSlug(p.slug === presetSlug ? null : p.slug)}
                  className={`rounded-[8px] border p-2 text-left transition-colors ${
                    presetSlug === p.slug
                      ? "border-safelight bg-[rgba(255,90,31,0.07)]"
                      : "border-line hover:border-[#33333a]"
                  }`}
                >
                  <span className="block text-[12px] font-medium leading-tight">
                    {p.name}
                  </span>
                  <span className="label mt-1 block !text-[8px]">
                    {p.family}
                    {p.move ? ` · ${p.move}` : ""}
                  </span>
                </button>
              ))}
            </div>
            {preset && (
              <p className="mt-2 text-[11.5px] leading-snug text-faint">{preset.desc}</p>
            )}
          </div>

          {/* submit */}
          <div className="border-t border-line-soft bg-sunken p-3">
            <button
              onClick={go}
              disabled={!prompt.trim() || !affordable}
              className="btn btn-primary !h-11 w-full !text-[14px]"
            >
              Develop
              <span className="mono ml-1 rounded-full bg-black/15 px-2 py-0.5 text-[11px]">
                {price.total} cr
              </span>
            </button>
            <div className="mt-2 flex items-center gap-2">
              <span className="label !text-[9px]">
                {model.cost}×{batch}
                {price.moveSurcharge ? ` + ${price.moveSurcharge} move` : ""} ·{" "}
                {state.credits} left
              </span>
              <span className="flex-1" />
              <span className="label !text-[9px]">⌘↵</span>
            </div>
            {!affordable && (
              <p className="mt-2 text-[11.5px] text-stop">
                Not enough credits.{" "}
                <Link href="/pricing" className="underline underline-offset-2">
                  Top up
                </Link>
                .
              </p>
            )}
            {err && <p className="mt-2 text-[11.5px] text-stop">{err}</p>}
          </div>
        </div>

        {/* what actually gets sent */}
        <button
          onClick={() => setShowFull((v) => !v)}
          className="label mt-3 block w-full text-left hover:!text-fg"
        >
          {showFull ? "▾" : "▸"} the prompt that actually gets sent
        </button>
        {showFull && (
          <p className="mono mt-2 rounded-[8px] border border-line bg-sunken p-3 text-[11px] leading-relaxed text-dim">
            {composed || "—"}
          </p>
        )}
      </div>

      {/* ------------------------------ results ------------------------------ */}
      <div>
        {lastJob ? (
          <>
            <div className="mb-3 flex items-baseline gap-3">
              <h2 className="display text-[26px]">
                {lastJob.status === "done" ? "Fixed" : "Developing"}
              </h2>
              <span className="label">
                {lastAssets.length} frame{lastAssets.length === 1 ? "" : "s"} ·{" "}
                {lastJob.cost} credits
              </span>
              <span className="flex-1" />
              <Link href="/library" className="label hover:!text-fg">
                contact sheet →
              </Link>
            </div>
            <div
              className={`grid gap-3 ${
                lastAssets.length > 2 ? "sm:grid-cols-3" : "sm:grid-cols-2"
              }`}
            >
              {lastAssets.map((a, i) => (
                <div key={a.id} className="rise" style={{ animationDelay: `${i * 70}ms` }}>
                  <Link href={`/a/${a.id}`} className="block">
                    <Frame asset={a} priority />
                  </Link>
                  <div className="mt-1.5 flex items-center gap-2">
                    <span className="label">seed {a.seed}</span>
                    <span className="flex-1" />
                    <button
                      className="label hover:!text-fg"
                      onClick={() => setLockSeed(a.seed)}
                      title="Lock this seed and change the prompt"
                    >
                      lock seed
                    </button>
                    <button
                      className="label hover:!text-fg"
                      onClick={() =>
                        dispatch({
                          t: "asset:patch",
                          id: a.id,
                          patch: { published: !a.published },
                        })
                      }
                    >
                      {a.published ? "on the wall" : "publish"}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : (
          <EmptyState onPick={(p) => setPrompt(p)} />
        )}
      </div>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (p: string) => void }) {
  return (
    <div className="flex min-h-[55vh] flex-col justify-center rounded-[14px] border border-dashed border-line px-6 py-12 text-center">
      <p className="display mx-auto max-w-[16ch] text-[34px] leading-[1.05] text-fg sm:text-[42px]">
        Nothing in the tray yet.
      </p>
      <p className="mx-auto mt-3 max-w-[46ch] text-[14px] leading-relaxed text-dim">
        Pick a preset on the left and describe the shot. The preset does the
        photographic direction so your prompt can stay about the subject.
      </p>
      <div className="mx-auto mt-6 flex max-w-[620px] flex-wrap justify-center gap-1.5">
        {IDEAS.map((i) => (
          <button
            key={i}
            onClick={() => onPick(i)}
            className="rounded-full border border-line px-3 py-1.5 text-[12px] text-dim transition-colors hover:border-[#3a3a42] hover:text-fg"
          >
            {i}
          </button>
        ))}
      </div>
    </div>
  );
}
