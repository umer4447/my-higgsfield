"use client";

/**
 * All client state: account, credit ledger, jobs, library.
 *
 * Persisted to localStorage so a visitor's work survives a refresh without
 * anyone having to sign up, and so the live link works for a stranger with no
 * backend account of any kind. Every read and write is wrapped -- private
 * windows and blocked site data must not break the app.
 *
 * The shape below is deliberately the shape a server would store, so swapping
 * the persistence layer for Postgres later is a change to this file and nothing
 * else.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from "react";
import { MODELS, Move, PLANS } from "./catalog";

const KEY = "darkroom:v1";

export type Kind = "image" | "motion";

export type Asset = {
  id: string;
  kind: Kind;
  url: string;
  /** what the user typed */
  prompt: string;
  /** what was actually sent, after the preset template */
  composed: string;
  modelId: string;
  presetSlug?: string | null;
  ratioId: string;
  seed: number;
  move?: Move | null;
  createdAt: number;
  author: string;
  published: boolean;
  likes: number;
  cost: number;
  /** seeded feed items carry a curated like count and a fake author */
  seeded?: boolean;
};

export type Job = {
  id: string;
  createdAt: number;
  status: "queued" | "running" | "done" | "failed";
  prompt: string;
  modelId: string;
  presetSlug?: string | null;
  ratioId: string;
  kind: Kind;
  batch: number;
  cost: number;
  assetIds: string[];
  error?: string;
};

export type LedgerRow = {
  id: string;
  ts: number;
  delta: number;
  reason: string;
};

export type State = {
  ready: boolean;
  handle: string | null;
  planId: string;
  credits: number;
  assets: Asset[];
  jobs: Job[];
  ledger: LedgerRow[];
  likedIds: string[];
  seenIntro: boolean;
};

const START_CREDITS = 40;

const initial: State = {
  ready: false,
  handle: null,
  planId: "darkroom-free",
  credits: START_CREDITS,
  assets: [],
  jobs: [],
  ledger: [],
  likedIds: [],
  seenIntro: false,
};

type Action =
  | { t: "hydrate"; state: Partial<State> }
  | { t: "claim"; handle: string }
  | { t: "signout" }
  | { t: "plan"; planId: string; credits: number }
  | { t: "spend"; amount: number; reason: string }
  | { t: "grant"; amount: number; reason: string }
  | { t: "job:add"; job: Job }
  | { t: "job:patch"; id: string; patch: Partial<Job> }
  | { t: "job:clear" }
  | { t: "asset:add"; asset: Asset }
  | { t: "asset:patch"; id: string; patch: Partial<Asset> }
  | { t: "asset:remove"; id: string }
  | { t: "like"; id: string }
  | { t: "intro" };

const rid = () =>
  Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

function reducer(s: State, a: Action): State {
  switch (a.t) {
    case "hydrate":
      return { ...s, ...a.state, ready: true };
    case "claim":
      return { ...s, handle: a.handle };
    case "signout":
      return { ...initial, ready: true, seenIntro: true };
    case "plan":
      return {
        ...s,
        planId: a.planId,
        credits: s.credits + a.credits,
        ledger: [
          { id: rid(), ts: Date.now(), delta: a.credits, reason: `Switched to ${a.planId}` },
          ...s.ledger,
        ].slice(0, 300),
      };
    case "spend":
      return {
        ...s,
        credits: Math.max(0, s.credits - a.amount),
        ledger: [
          { id: rid(), ts: Date.now(), delta: -a.amount, reason: a.reason },
          ...s.ledger,
        ].slice(0, 300),
      };
    case "grant":
      return {
        ...s,
        credits: s.credits + a.amount,
        ledger: [
          { id: rid(), ts: Date.now(), delta: a.amount, reason: a.reason },
          ...s.ledger,
        ].slice(0, 300),
      };
    case "job:add":
      return { ...s, jobs: [a.job, ...s.jobs].slice(0, 60) };
    case "job:patch":
      return {
        ...s,
        jobs: s.jobs.map((j) => (j.id === a.id ? { ...j, ...a.patch } : j)),
      };
    case "job:clear":
      return { ...s, jobs: s.jobs.filter((j) => j.status !== "done" && j.status !== "failed") };
    case "asset:add":
      return { ...s, assets: [a.asset, ...s.assets].slice(0, 400) };
    case "asset:patch":
      return {
        ...s,
        assets: s.assets.map((x) => (x.id === a.id ? { ...x, ...a.patch } : x)),
      };
    case "asset:remove":
      return { ...s, assets: s.assets.filter((x) => x.id !== a.id) };
    case "like": {
      const on = s.likedIds.includes(a.id);
      return {
        ...s,
        likedIds: on ? s.likedIds.filter((x) => x !== a.id) : [...s.likedIds, a.id],
      };
    }
    case "intro":
      return { ...s, seenIntro: true };
    default:
      return s;
  }
}

type Ctx = {
  state: State;
  dispatch: React.Dispatch<Action>;
  /** cost-aware guard used by the composer */
  canAfford: (n: number) => boolean;
  planName: string;
};

const StoreCtx = createContext<Ctx | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const loaded = useRef(false);

  useEffect(() => {
    let saved: Partial<State> = {};
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) saved = JSON.parse(raw);
    } catch {
      /* private window, blocked storage — start clean, still works */
    }
    // never restore in-flight jobs; they cannot survive a reload
    if (saved.jobs) {
      saved.jobs = saved.jobs.filter(
        (j) => j.status === "done" || j.status === "failed",
      );
    }
    dispatch({ t: "hydrate", state: saved });
    loaded.current = true;
  }, []);

  useEffect(() => {
    if (!loaded.current || !state.ready) return;
    try {
      const { ready: _ready, ...rest } = state;
      void _ready;
      localStorage.setItem(KEY, JSON.stringify(rest));
    } catch {
      /* over quota or blocked — the session still works, it just won't persist */
    }
  }, [state]);

  const canAfford = useCallback((n: number) => state.credits >= n, [state.credits]);

  const planName = useMemo(
    () => PLANS.find((p) => p.id === state.planId)?.name ?? "Contact",
    [state.planId],
  );

  return (
    <StoreCtx.Provider value={{ state, dispatch, canAfford, planName }}>
      {children}
    </StoreCtx.Provider>
  );
}

export function useStore() {
  const c = useContext(StoreCtx);
  if (!c) throw new Error("useStore outside StoreProvider");
  return c;
}

export const newId = rid;

export function modelName(id: string) {
  return MODELS.find((m) => m.id === id)?.name ?? id;
}
