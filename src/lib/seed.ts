/**
 * The Wall — what a new visitor sees before they have made anything.
 *
 * These are real prompts against real models. Nothing here is a stock photo:
 * each tile is generated on demand from the parameters below, which is also why
 * every one of them can be opened, read and remixed. That is the single biggest
 * departure from the product this rebuilds, where the feed is full of work you
 * cannot learn anything from.
 */

import { Asset } from "./store";
import { frameUrl } from "./gen";
import { modelById, presetBySlug, ratioById, Move } from "./catalog";

type Spec = {
  prompt: string;
  model: string;
  preset?: string;
  ratio: string;
  seed: number;
  author: string;
  likes: number;
  move?: Move;
};

const SPECS: Spec[] = [
  {
    prompt: "a courier asleep against his bike outside a 24 hour noodle shop",
    model: "halide-2",
    preset: "anamorphic-night",
    ratio: "9:16",
    seed: 4411,
    author: "hana.k",
    likes: 2840,
  },
  {
    prompt: "a single ripe persimmon on a cracked ceramic plate",
    model: "halide-flash",
    preset: "table-top",
    ratio: "1:1",
    seed: 8802,
    author: "studio.morn",
    likes: 1190,
  },
  {
    prompt: "a rally car mid-slide throwing gravel over a spectator's head",
    model: "reel-9",
    preset: "impact-frame",
    ratio: "16:9",
    seed: 1177,
    author: "dustline",
    likes: 5210,
  },
  {
    prompt: "a woman in a yellow raincoat on a ferry deck, wind in her hair",
    model: "halide-2",
    preset: "portra-soft",
    ratio: "4:5",
    seed: 3390,
    author: "j.okonkwo",
    likes: 3105,
  },
  {
    prompt: "the stairwell of a 1970s brutalist library, empty",
    model: "halide-flash",
    preset: "brutal-concrete",
    ratio: "4:5",
    seed: 1971,
    author: "concreteclub",
    likes: 890,
  },
  {
    prompt: "a fisherman mending nets on a harbour wall at dawn",
    model: "reel-mini",
    preset: "cold-open",
    ratio: "21:9",
    seed: 621,
    author: "north.reel",
    likes: 4402,
  },
  {
    prompt: "a chrome perfume bottle shaped like a river stone",
    model: "reel-9",
    preset: "product-plinth",
    ratio: "1:1",
    seed: 2024,
    author: "atelier.nn",
    likes: 6720,
  },
  {
    prompt: "teenagers on a rooftop watching a thunderstorm roll in",
    model: "halide-flash",
    preset: "sunfade",
    ratio: "16:9",
    seed: 1993,
    author: "vhs.summer",
    likes: 2277,
  },
  {
    prompt: "a dense forest road seen from a low drone",
    model: "halide-flash",
    preset: "infrared",
    ratio: "16:9",
    seed: 707,
    author: "false.colour",
    likes: 1533,
  },
  {
    prompt: "a chef plating in a stainless kitchen under one hanging lamp",
    model: "halide-flash",
    preset: "hard-flash",
    ratio: "4:5",
    seed: 5150,
    author: "pass.line",
    likes: 980,
  },
  {
    prompt: "a lone lighthouse keeper crossing the causeway at high tide",
    model: "reel-9",
    preset: "earth-pull",
    ratio: "21:9",
    seed: 88,
    author: "north.reel",
    likes: 7310,
  },
  {
    prompt: "a night market stall selling grilled squid, crowded",
    model: "reel-mini",
    preset: "whip-cut",
    ratio: "9:16",
    seed: 4242,
    author: "hana.k",
    likes: 3901,
  },
  {
    prompt: "a cyclist climbing an alpine switchback in fog",
    model: "halide-flash",
    preset: "riso-print",
    ratio: "4:5",
    seed: 1010,
    author: "press.and.fold",
    likes: 760,
  },
  {
    prompt: "an empty swimming pool lit from below at night",
    model: "halide-2",
    preset: "sodium-vapour",
    ratio: "16:9",
    seed: 3003,
    author: "afterhours",
    likes: 2140,
  },
  {
    prompt: "a woman walking to work as her belongings hang in the air",
    model: "reel-9",
    preset: "float-away",
    ratio: "9:16",
    seed: 9090,
    author: "gravity.off",
    likes: 8840,
  },
  {
    prompt: "a container port at midday from a high window",
    model: "halide-flash",
    preset: "miniature-world",
    ratio: "16:9",
    seed: 313,
    author: "tiny.industry",
    likes: 1620,
  },
  {
    prompt: "two mechanics sharing a flask outside a roadside garage",
    model: "plate",
    preset: "kodachrome-64",
    ratio: "4:5",
    seed: 640,
    author: "roadside.64",
    likes: 3350,
  },
  {
    prompt: "a commuter standing still while the concourse blurs past",
    model: "reel-9",
    preset: "crowd-single",
    ratio: "9:16",
    seed: 1800,
    author: "one.eighth",
    likes: 5980,
  },
  {
    prompt: "a greenhouse full of tomato vines in low winter sun",
    model: "halide-flash",
    preset: "portra-soft",
    ratio: "1:1",
    seed: 2211,
    author: "studio.morn",
    likes: 1044,
  },
  {
    prompt: "a taxi rank outside a station in heavy rain, seen from above",
    model: "reel-mini",
    preset: "anamorphic-night",
    ratio: "4:5",
    seed: 6060,
    author: "afterhours",
    likes: 2610,
  },
  {
    prompt: "a sculptor's hands covered in wet clay",
    model: "plate",
    preset: "hard-flash",
    ratio: "1:1",
    seed: 404,
    author: "atelier.nn",
    likes: 1870,
  },
  {
    prompt: "a desert road with a single water tower on the horizon",
    model: "halide-flash",
    preset: "earth-pull",
    ratio: "21:9",
    seed: 1500,
    author: "dustline",
    likes: 2990,
  },
  {
    prompt: "a record shop owner behind a counter of vinyl",
    model: "halide-flash",
    preset: "kodachrome-64",
    ratio: "4:5",
    seed: 3312,
    author: "roadside.64",
    likes: 1425,
  },
  {
    prompt: "a rain-soaked crosswalk in a neon shopping district",
    model: "reel-9",
    preset: "anamorphic-night",
    ratio: "9:16",
    seed: 777,
    author: "hana.k",
    likes: 9120,
  },
];

export const SEED_ASSETS: Asset[] = SPECS.map((s, i) => {
  const model = modelById(s.model)!;
  const preset = s.preset ? presetBySlug(s.preset) : null;
  const ratio = ratioById(s.ratio);
  const move = s.move ?? preset?.move ?? null;
  const kind = model.mode === "motion" ? "motion" : "image";
  return {
    id: `wall-${i.toString().padStart(2, "0")}`,
    kind,
    url: frameUrl({ prompt: s.prompt, model, ratio, preset, seed: s.seed, move }),
    prompt: s.prompt,
    composed: preset ? preset.template.replace("{prompt}", s.prompt) : s.prompt,
    modelId: model.id,
    presetSlug: preset?.slug ?? null,
    ratioId: ratio.id,
    seed: s.seed,
    move: kind === "motion" ? move : null,
    createdAt: Date.now() - (i + 1) * 5_400_000,
    author: s.author,
    published: true,
    likes: s.likes,
    cost: model.cost,
    seeded: true,
  };
});
