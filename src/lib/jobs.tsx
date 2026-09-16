"use client";

/**
 * The job engine.
 *
 * A submission becomes a job with N outputs. Credits are debited up front, the
 * assets are created immediately with their deterministic URLs, and the runner
 * preloads each frame off-screen so a job keeps progressing while you browse
 * somewhere else. That is the point of the tray: generation should never hold
 * you hostage on the page you started it from.
 *
 * Failed outputs are refunded. Nobody should pay for a frame they did not get.
 */

import { useCallback, useEffect, useRef } from "react";
import { useStore, Asset, Job, newId } from "./store";
import { Model, Preset, Ratio } from "./catalog";
import { composePrompt, frameUrl, priceJob, randomSeed } from "./gen";

export type Submission = {
  prompt: string;
  model: Model;
  ratio: Ratio;
  preset?: Preset | null;
  batch: number;
  seed?: number | null;
};

export function useSubmit() {
  const { state, dispatch } = useStore();

  return useCallback(
    (sub: Submission): { ok: boolean; reason?: string; jobId?: string } => {
      const prompt = sub.prompt.trim();
      if (!prompt) return { ok: false, reason: "Write a prompt first." };

      const { total } = priceJob(sub.model, sub.batch, sub.preset);
      if (state.credits < total)
        return {
          ok: false,
          reason: `That costs ${total} credits and you have ${state.credits}.`,
        };

      const jobId = newId();
      const kind = sub.model.mode === "motion" ? "motion" : "image";
      const assetIds: string[] = [];

      for (let i = 0; i < sub.batch; i++) {
        const seed = sub.seed != null ? sub.seed + i : randomSeed();
        const move = kind === "motion" ? sub.preset?.move ?? "push" : null;
        const asset: Asset = {
          id: newId(),
          kind,
          url: frameUrl({
            prompt,
            model: sub.model,
            ratio: sub.ratio,
            preset: sub.preset,
            seed,
            move,
          }),
          prompt,
          composed: composePrompt(prompt, sub.preset),
          modelId: sub.model.id,
          presetSlug: sub.preset?.slug ?? null,
          ratioId: sub.ratio.id,
          seed,
          move,
          createdAt: Date.now(),
          author: state.handle ?? "you",
          published: false,
          likes: 0,
          cost: sub.model.cost,
        };
        assetIds.push(asset.id);
        dispatch({ t: "asset:add", asset });
      }

      const job: Job = {
        id: jobId,
        createdAt: Date.now(),
        status: "queued",
        prompt,
        modelId: sub.model.id,
        presetSlug: sub.preset?.slug ?? null,
        ratioId: sub.ratio.id,
        kind,
        batch: sub.batch,
        cost: total,
        assetIds,
      };

      dispatch({ t: "spend", amount: total, reason: `${sub.model.name} × ${sub.batch}` });
      dispatch({ t: "job:add", job });
      return { ok: true, jobId };
    },
    [state.credits, state.handle, dispatch],
  );
}

/**
 * Mounted once in the shell. Drives queued jobs to completion by preloading
 * their frames, independent of whatever is on screen.
 */
export function JobRunner() {
  const { state, dispatch } = useStore();
  const driving = useRef<Set<string>>(new Set());

  useEffect(() => {
    for (const job of state.jobs) {
      if (job.status !== "queued" || driving.current.has(job.id)) continue;
      driving.current.add(job.id);
      dispatch({ t: "job:patch", id: job.id, patch: { status: "running" } });

      const assets = state.assets.filter((a) => job.assetIds.includes(a.id));
      let failed = 0;

      Promise.all(
        assets.map(
          (a) =>
            new Promise<void>((resolve) => {
              const img = new Image();
              const done = () => resolve();
              img.onload = done;
              img.onerror = () => {
                failed += 1;
                dispatch({ t: "asset:remove", id: a.id });
                done();
              };
              img.src = a.url;
              // a frame that has not landed in two minutes is not landing
              setTimeout(() => {
                if (!img.complete) {
                  failed += 1;
                  dispatch({ t: "asset:remove", id: a.id });
                  resolve();
                }
              }, 120_000);
            }),
        ),
      ).then(() => {
        const model = assets[0];
        if (failed > 0 && model) {
          const refund = Math.round((job.cost / job.batch) * failed);
          dispatch({
            t: "grant",
            amount: refund,
            reason: `Refund — ${failed} frame${failed > 1 ? "s" : ""} failed`,
          });
        }
        dispatch({
          t: "job:patch",
          id: job.id,
          patch:
            failed === job.batch
              ? { status: "failed", error: "No frames came back. Credits refunded." }
              : { status: "done" },
        });
      });
    }
  }, [state.jobs, state.assets, dispatch]);

  return null;
}
