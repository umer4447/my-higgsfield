/**
 * Client-side validation, mirroring the Pydantic models field for field.
 *
 * This is a UX feature, not a control: it saves a round trip and puts the error
 * next to the field. The server is the contract, and re-validates everything.
 * `tests/schema-parity.test.ts` asserts the two agree, so a bound changed on one
 * side fails the build until it changes on the other.
 */

import { number, object, string } from "yup";

export const PROMPT_MIN = 3;
export const PROMPT_MAX = 2000;
export const BATCH_MIN = 1;
/** The global ceiling, matching CHECK (batch BETWEEN 1 AND 8). The real caps
 *  are per-model and per-plan and only the server knows them. */
export const BATCH_MAX = 8;
export const SEED_MIN = 0;
export const SEED_MAX = 9_999_999;
export const SEARCH_MIN = 2;
export const SEARCH_MAX = 100;
export const HANDLE_MIN = 3;
export const HANDLE_MAX = 32;

const SLUG = /^[a-z0-9-]{2,64}$/;
const RATIO = /^\d{1,2}:\d{1,2}$/;
const HANDLE = /^[a-z0-9._-]{3,32}$/;

export const submitSchema = object({
  prompt: string()
    .trim()
    .min(PROMPT_MIN, "A few more words.")
    .max(PROMPT_MAX, "That is longer than any model will read.")
    .required("Write a prompt first."),
  modelId: string().matches(SLUG, "Pick a model.").required(),
  ratioId: string().matches(RATIO, "Pick a frame.").required(),
  presetSlug: string().matches(SLUG).nullable().defined(),
  batch: number().integer().min(BATCH_MIN).max(BATCH_MAX).required(),
  seed: number().integer().min(SEED_MIN).max(SEED_MAX).nullable().defined(),
}).noUnknown();

export const quoteSchema = object({
  modelId: string().matches(SLUG).required(),
  batch: number().integer().min(BATCH_MIN).max(BATCH_MAX).required(),
  presetSlug: string().matches(SLUG).nullable().defined(),
}).noUnknown();

export const searchSchema = string().trim().min(SEARCH_MIN).max(SEARCH_MAX);

export const handleSchema = string()
  .trim()
  .lowercase()
  .min(HANDLE_MIN)
  .max(HANDLE_MAX)
  .matches(
    HANDLE,
    "Handles are 3-32 characters: lowercase letters, digits, dot, underscore or hyphen.",
  )
  .required();

/** First error message per field, shaped for rendering next to an input. */
export async function validate<T extends object>(
  schema: { validate: (v: unknown, o: object) => Promise<unknown> },
  value: T,
): Promise<{ ok: true } | { ok: false; errors: Record<string, string> }> {
  try {
    await schema.validate(value, { abortEarly: false, stripUnknown: false });
    return { ok: true };
  } catch (err) {
    const errors: Record<string, string> = {};
    const inner = (err as { inner?: { path?: string; message: string }[] }).inner ?? [];
    for (const e of inner) {
      if (e.path && !errors[e.path]) errors[e.path] = e.message;
    }
    if (Object.keys(errors).length === 0) {
      errors._ = (err as Error).message;
    }
    return { ok: false, errors };
  }
}
