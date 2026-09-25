"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, type Job, type Mode, api, newIdempotencyKey } from "@/lib/api";
import { submitSchema, validate } from "@/lib/schemas/job";
import { useStore } from "@/lib/store";
import Frame from "./Frame";

const PRESET_FAMILIES = ["CAMERA", "LIGHT", "STOCK", "WORLD"] as const;

const IDEAS = [
  "a fishmonger hosing down the floor at closing time",
  "a satellite dish farm in the desert at dusk",
  "a ballet dancer taping her feet backstage",
  "an overgrown petrol station reclaimed by ivy",
  "two brothers arguing over a car engine",
  "a hotel corridor with one door open",
];

export default function Composer() {
  const params = useSearchParams();
  const { me, catalog, ready, trackJob, refreshMe } = useStore();
  const areaRef = useRef<HTMLTextAreaElement>(null);

  // Memoised so the dependency arrays below can name them honestly instead of
  // being silenced: a fresh array each render would loop.
  const MODELS = useMemo(() => catalog?.models ?? [], [catalog]);
  const PRESETS = useMemo(() => catalog?.presets ?? [], [catalog]);
  const RATIOS = useMemo(() => catalog?.ratios ?? [], [catalog]);
  const modelById = (id: string) => MODELS.find((m) => m.id === id);
  const presetBySlug = (slug: string) => PRESETS.find((p) => p.slug === slug);
  const ratioById = (id: string) => RATIOS.find((r) => r.id === id) ?? RATIOS[0];

  /* ---- remix: hydrate from the query string ----
     Read during the first render rather than in an effect. An effect would
     paint the default composer, then replace it, which is a visible flash on
     every Remix click. */
  const qsModel = params.get("model");
  const qsPreset = params.get("preset");
  const qsRatio = params.get("ratio");
  const qsSeed = params.get("seed");
  const remixModel = qsModel && modelById(qsModel) ? qsModel : null;

  const [mode, setMode] = useState<Mode>(
    remixModel ? modelById(remixModel)!.mode : "image",
  );
  const [prompt, setPrompt] = useState(() => params.get("prompt") ?? "");
  const [modelId, setModelId] = useState(remixModel ?? "halide-2");
  const [presetSlug, setPresetSlug] = useState<string | null>(
    qsPreset && presetBySlug(qsPreset) ? qsPreset : null,
  );
  const [ratioId, setRatioId] = useState(
    qsRatio && RATIOS.some((x) => x.id === qsRatio) ? qsRatio : "4:5",
  );
  const [batch, setBatch] = useState(2);
  const [lockSeed, setLockSeed] = useState<number | null>(
    qsSeed && !Number.isNaN(Number(qsSeed)) ? Number(qsSeed) : null,
  );
  const [family, setFamily] = useState<string>("All");
  const [err, setErr] = useState<string | null>(null);
  const [lastJobId, setLastJobId] = useState<string | null>(null);
  const [showFull, setShowFull] = useState(false);

  /* Focus the prompt when arriving from a Remix link. Focus is a DOM effect,
     which is what effects are for; the state above is not. */
  useEffect(() => {
    if (params.get("prompt")) {
      const t = setTimeout(() => areaRef.current?.focus(), 60);
      return () => clearTimeout(t);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const models = useMemo(() => MODELS.filter((m) => m.mode === mode), [MODELS, mode]);
  const model = modelById(modelId) ?? models[0];
  const preset = presetSlug ? presetBySlug(presetSlug) ?? null : null;
  const ratio = ratioById(ratioId);

  /* Keep model, batch and preset consistent with the mode. Adjusted during
     render rather than in effects: an effect would let one frame paint with a
     motion preset on an image model, and the cost readout would be wrong for
     that frame. */
  if (model && model.mode !== mode && models.length) {
    setModelId(models[0].id);
  }
  if (model && batch > model.maxBatch) {
    setBatch(model.maxBatch);
  }
  /* a motion job needs a preset that carries a camera move */
  if (mode === "motion" && preset && !preset.move) {
    setPresetSlug(null);
  }

  const visiblePresets = useMemo(
    () =>
      PRESETS.filter(
        (p) =>
          (mode === "image" ? true : !!p.move) &&
          (family === "All" || p.family === family),
      ),
    [PRESETS, mode, family],
  );

  /* The cost on the button comes from the server that will charge it, quoted
     by the same function that performs the debit. Rendered optimistically from
     the catalog first so the number does not flicker while the quote lands. */
  const optimistic = model
    ? model.creditCost * batch + (preset?.move ? batch : 0)
    : 0;
  const [quoted, setQuoted] = useState<number | null>(null);
  const total = quoted ?? optimistic;
  const affordable = (me?.credits ?? 0) >= total;
  const composed = preset
    ? preset.template.replace("{prompt}", prompt.trim() || "a striking subject")
    : prompt.trim();

  useEffect(() => {
    if (!model || !me) return;
    const controller = new AbortController();
    api
      .quote({ modelId: model.id, batch, presetSlug: preset?.slug ?? null })
      .then((q) => {
        if (!controller.signal.aborted) setQuoted(q.total);
      })
      .catch(() => setQuoted(null));
    return () => controller.abort();
  }, [model, batch, preset, me]);

  const [lastJob, setLastJob] = useState<Job | null>(null);
  const [pending, setPending] = useState(false);
  const keyRef = useRef<string | null>(null);

  /* Keep the result panel in step with the tray: the SSE stream updates the
     store, and the job we just submitted is in it. */
  const { jobs } = useStore();
  const trackedJob = lastJobId ? jobs.find((j) => j.id === lastJobId) ?? lastJob : null;
  const lastAssets = trackedJob?.outputs ?? [];

  async function go() {
    if (pending || !model || !ratio) return;
    setErr(null);

    const body = {
      prompt: prompt.trim(),
      modelId: model.id,
      ratioId: ratio.id,
      presetSlug: preset?.slug ?? null,
      batch,
      seed: lockSeed,
    };

    // Yup first: an error next to the field beats a round trip.
    const check = await validate(submitSchema, body);
    if (!check.ok) {
      setErr(Object.values(check.errors)[0] ?? "Check the form.");
      return;
    }

    // One key per submission intent, held across retries of that submission.
    keyRef.current = keyRef.current ?? newIdempotencyKey();
    setPending(true);
    try {
      const job = await api.submit(body, keyRef.current);
      keyRef.current = null;
      setLastJob(job);
      setLastJobId(job.id);
      trackJob(job);
      await refreshMe();
    } catch (error) {
      if (error instanceof ApiError) {
        setErr(
          error.retryAfter
            ? `${error.detail} (retry in ${error.retryAfter}s)`
            : error.detail,
        );
        // A transient failure keeps the key, so a retry is the same submission.
        if (!error.isTransient) keyRef.current = null;
      } else {
        setErr("Could not reach the server.");
      }
    } finally {
      setPending(false);
    }
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        void go();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  /* The composer is entirely catalog-driven: models, presets, ratios and the
     price all come from the server. Rendering before it arrives means a
     controls panel with no controls, so hold the frame instead. Reaching
     /create directly, rather than from a Remix link, is exactly that case. */
  if (!ready || !catalog || !model || !ratio) {
    return (
      <div className="mx-auto max-w-[1500px] px-6 py-24" data-testid="composer-loading">
        <div className="label">loading composer…</div>
      </div>
    );
  }

  return (
    <div className="mx-auto grid max-w-[1500px] gap-6 px-4 pb-32 pt-6 sm:px-6 lg:grid-cols-[404px_1fr]">
      {/* ------------------------------ controls ------------------------------ */}
      <div className="lg:sticky lg:top-[73px] lg:max-h-[calc(100vh-88px)] lg:self-start lg:overflow-y-auto lg:pr-1">
        {/* no overflow-hidden here: it would kill position:sticky on the submit bar */}
        <div className="card">
          {/* mode */}
          <div className="grid grid-cols-2 overflow-hidden rounded-t-[14px] border-b border-line-soft">
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
                  <span className="mono shrink-0 text-[11px] text-dim">{m.creditCost}cr</span>
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
            <div className="grid max-h-[176px] grid-cols-2 gap-1.5 overflow-y-auto pr-1">
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
              <p className="mt-2 text-[11.5px] leading-snug text-faint">{preset.description}</p>
            )}
          </div>

          {/* submit */}
          <div className="sticky bottom-0 z-20 rounded-b-[14px] border-t border-line bg-sunken/95 p-3 backdrop-blur-md">
            <button
              onClick={() => void go()}
              data-testid="develop"
              disabled={!prompt.trim() || !affordable || pending || !ready}
              className="btn btn-primary !h-11 w-full !text-[14px]"
            >
              {pending ? "Submitting…" : "Develop"}
              <span
                data-testid="develop-cost"
                className="mono ml-1 rounded-full bg-black/15 px-2 py-0.5 text-[11px]"
              >
                {total} cr
              </span>
            </button>
            <div className="mt-2 flex items-center gap-2">
              <span className="label !text-[9px]">
                {model ? model.creditCost : 0}×{batch}
                {preset?.move ? ` + ${batch} move` : ""} ·{" "}
                {me?.credits ?? 0} left
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
            {err && (
              <p data-testid="composer-error" className="mt-2 text-[11.5px] text-stop">
                {err}
              </p>
            )}
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
        {trackedJob ? (
          <>
            <div className="mb-3 flex items-baseline gap-3">
              <h2 data-testid="result-heading" className="display text-[26px]">
                {trackedJob.status === "succeeded"
                  ? "Fixed"
                  : trackedJob.status === "partial"
                    ? "Partly fixed"
                    : trackedJob.status === "failed"
                      ? "Lost"
                      : trackedJob.status === "cancelled"
                        ? "Cancelled"
                        : "Developing"}
              </h2>
              <span className="label" data-testid="result-meta">
                {lastAssets.length} frame{lastAssets.length === 1 ? "" : "s"} ·{" "}
                {trackedJob.creditsDebited} credits
                {trackedJob.creditsRefunded > 0
                  ? ` · ${trackedJob.creditsRefunded} refunded`
                  : ""}
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
              {lastAssets.map((o, i) => (
                <ResultTile
                  key={o.id}
                  output={o}
                  job={trackedJob}
                  index={i}
                  onLockSeed={() => setLockSeed(o.seed)}
                />
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

function ResultTile({
  output,
  job,
  index,
  onLockSeed,
}: {
  output: Job["outputs"][number];
  job: Job;
  index: number;
  onLockSeed: () => void;
}) {
  const [published, setPublished] = useState(false);
  const [busy, setBusy] = useState(false);

  async function togglePublish() {
    if (busy || output.status !== "ready") return;
    setBusy(true);
    const next = !published;
    try {
      await api.publish(output.id, next);
      setPublished(next);
    } catch {
      /* the server is authoritative; leave the label as it was */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="rise"
      data-testid="result-tile"
      data-output-status={output.status}
      style={{ animationDelay: `${index * 70}ms` }}
    >
      <Link href={`/a/${output.id}`} className="block">
        <Frame
          asset={{
            id: output.id,
            mode: job.mode,
            status: output.status,
            prompt: job.prompt,
            url: output.url,
            move: job.move,
            width: output.width,
            height: output.height,
          }}
          priority
        />
      </Link>
      <div className="mt-1.5 flex items-center gap-2">
        <span className="label">seed {output.seed}</span>
        <span className="flex-1" />
        <button
          className="label hover:!text-fg"
          onClick={onLockSeed}
          title="Lock this seed and change the prompt"
        >
          lock seed
        </button>
        <button
          className="label hover:!text-fg disabled:opacity-40"
          onClick={() => void togglePublish()}
          disabled={output.status !== "ready" || busy}
          data-testid="publish-toggle"
        >
          {published ? "on the wall" : "publish"}
        </button>
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
