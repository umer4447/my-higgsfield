"use client";

/**
 * Session, credits and the job tray -- all server state now.
 *
 * What used to live here: a localStorage reducer holding the account, the credit
 * ledger, every asset and every job. That made credits a number the user owned,
 * which is not a currency. The server owns all of it; this file is the client's
 * view of it.
 *
 * A visitor still gets a working composer with no sign-up, because anonymity is
 * a real account server-side rather than an absence of one.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ApiError,
  type Catalog,
  type Job,
  type Me,
  api,
  subscribeToJobs,
} from "@/lib/api";

type Ctx = {
  /** null until the session resolves; the UI renders a loading state. */
  me: Me | null;
  catalog: Catalog | null;
  jobs: Job[];
  ready: boolean;
  /** Set when the backend cannot be reached at all. */
  offline: boolean;
  refreshMe: () => Promise<void>;
  refreshJobs: () => Promise<void>;
  trackJob: (job: Job) => void;
  claim: (handle: string) => Promise<Me>;
  setPlan: (planId: string) => Promise<Me>;
  cancelJob: (id: string) => Promise<void>;
};

const StoreContext = createContext<Ctx | null>(null);

const ACTIVE: Job["status"][] = ["queued", "running"];

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refreshMe = useCallback(async () => {
    // A readable marker cookie says whether a session exists. Without it, go
    // straight to sign-in: asking /v1/me first would make every first visit
    // log a 401 in the console for nothing.
    const hasSession =
      typeof document !== "undefined" && document.cookie.includes("dr_session=1");
    if (!hasSession) {
      setMe(await api.signInAnonymously());
      return;
    }
    try {
      setMe(await api.me());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setMe(await api.signInAnonymously());
      } else {
        throw err;
      }
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    const page = await api.jobs({ limit: 8 });
    setJobs(page.data);
  }, []);

  // Boot: catalog and session in parallel, then the job tray.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cat] = await Promise.all([api.catalog(), refreshMe()]);
        if (cancelled) return;
        setCatalog(cat);
        await refreshJobs();
      } catch {
        if (!cancelled) setOffline(true);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshMe, refreshJobs]);

  /** Live job transitions, with polling as the documented fallback. */
  useEffect(() => {
    if (!me) return;
    let failures = 0;

    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(() => {
        void refreshJobs();
        void refreshMe();
      }, 5000);
    };

    const stop = subscribeToJobs(
      (event) => {
        if (event.event === "ready") return;
        void refreshJobs();
        if (event.event === "credits.changed" || event.event === "job.updated") {
          void refreshMe();
        }
      },
      () => {
        failures += 1;
        // Mobile Safari and corporate proxies both drop long-lived
        // connections, so two failures means stop trying and poll.
        if (failures >= 2) startPolling();
      },
    );

    return () => {
      stop();
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [me, refreshJobs, refreshMe]);

  const trackJob = useCallback((job: Job) => {
    setJobs((prev) => [job, ...prev.filter((j) => j.id !== job.id)].slice(0, 8));
  }, []);

  const claim = useCallback(async (handle: string) => {
    const next = await api.claim(handle);
    setMe(next);
    return next;
  }, []);

  const setPlan = useCallback(async (planId: string) => {
    const next = await api.setPlan(planId);
    setMe(next);
    return next;
  }, []);

  const cancelJob = useCallback(
    async (id: string) => {
      const job = await api.cancel(id);
      setJobs((prev) => prev.map((j) => (j.id === id ? job : j)));
      await refreshMe();
    },
    [refreshMe],
  );

  const value = useMemo<Ctx>(
    () => ({
      me,
      catalog,
      jobs,
      ready,
      offline,
      refreshMe,
      refreshJobs,
      trackJob,
      claim,
      setPlan,
      cancelJob,
    }),
    [me, catalog, jobs, ready, offline, refreshMe, refreshJobs, trackJob, claim, setPlan, cancelJob],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): Ctx {
  const ctx = useContext(StoreContext);
  if (!ctx) throw new Error("useStore must be used inside StoreProvider");
  return ctx;
}

/** Jobs the tray should show as live. */
export function activeJobs(jobs: Job[]): Job[] {
  return jobs.filter((j) => ACTIVE.includes(j.status));
}

export function modelName(catalog: Catalog | null, id: string): string {
  return catalog?.models.find((m) => m.id === id)?.name ?? id;
}

export function presetName(catalog: Catalog | null, slug: string | null): string | null {
  if (!slug) return null;
  return catalog?.presets.find((p) => p.slug === slug)?.name ?? slug;
}

export function ratioOf(catalog: Catalog | null, id: string) {
  return catalog?.ratios.find((r) => r.id === id) ?? { width: 832, height: 832 };
}
