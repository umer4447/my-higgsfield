/**
 * Turning a set of composer parameters into an actual generated frame.
 *
 * Images are real. They are produced by a keyless diffusion endpoint, which is
 * deliberate: the live link has to work for a stranger who has no API key of
 * their own, and it has to keep working when a hundred people open it at once.
 *
 * Motion is a real job that produces a real generated keyframe, then plays it
 * under the camera move the preset asks for. The frame is generated; the move is
 * rendered in the browser. That is stated plainly in the UI rather than dressed
 * up as a video model — see the note on every motion result.
 */

import { Preset, Ratio, Model, Move } from "./catalog";

const ENDPOINT = "https://image.pollinations.ai/prompt/";

export type GenParams = {
  prompt: string;
  model: Model;
  ratio: Ratio;
  preset?: Preset | null;
  seed: number;
  move?: Move | null;
};

/** Apply the preset template. This is the prompt that is actually sent. */
export function composePrompt(prompt: string, preset?: Preset | null): string {
  const base = prompt.trim();
  if (!preset) return base;
  return preset.template.replace("{prompt}", base || "a striking subject");
}

export function frameUrl(p: GenParams): string {
  const full = composePrompt(p.prompt, p.preset);
  const engine = p.model.engine;
  const qs = new URLSearchParams({
    width: String(p.ratio.w),
    height: String(p.ratio.h),
    seed: String(p.seed),
    model: engine,
    nologo: "true",
    referrer: "darkroom",
  });
  return `${ENDPOINT}${encodeURIComponent(full)}?${qs.toString()}`;
}

export function randomSeed() {
  return Math.floor(Math.random() * 9_000_000) + 1000;
}

/** Credit cost for a whole submission, itemised so the UI can explain it. */
export function priceJob(model: Model, batch: number, preset?: Preset | null) {
  const base = model.cost * batch;
  // presets that drive a camera move cost one extra credit per output to render
  const moveSurcharge = preset?.move ? batch : 0;
  return { base, moveSurcharge, total: base + moveSurcharge };
}

export const MOVE_CLASS: Record<Move, string> = {
  push: "mv mv-push",
  pull: "mv mv-pull",
  orbit: "mv mv-orbit",
  whip: "mv mv-whip",
  crane: "mv mv-crane",
  float: "mv mv-float",
  shake: "mv mv-shake",
  dolly: "mv mv-dolly",
};
