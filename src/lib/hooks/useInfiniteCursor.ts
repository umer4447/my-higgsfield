"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type Page } from "@/lib/api";

/**
 * Keyset pagination, client side.
 *
 * Cursors are opaque and signed, so they are never constructed here -- only
 * echoed back. Every fetch is cancellable: without that, a slow response can
 * land after a newer one and repaint stale results, which is a correctness bug
 * rather than a performance one.
 *
 * No state is written synchronously in an effect body. `loading` starts true
 * and every other update happens after an await, which is what keeps this a
 * subscription to an external system rather than a cascading render.
 */
export function useInfiniteCursor<T extends { id: string }>(
  fetchPage: (cursor: string | null, signal: AbortSignal) => Promise<Page<T>>,
  deps: unknown[],
) {
  const [items, setItems] = useState<T[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const seen = useRef(new Set<string>());

  const load = useCallback(
    async (next: string | null, replace: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const page = await fetchPage(next, controller.signal);
        if (controller.signal.aborted) return;
        if (replace) seen.current = new Set();
        const fresh = page.data.filter((row) => !seen.current.has(row.id));
        for (const row of fresh) seen.current.add(row.id);
        setItems((prev) => (replace ? page.data : [...prev, ...fresh]));
        setCursor(page.meta.nextCursor);
        setHasMore(page.meta.hasMore);
        setError(null);
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof ApiError ? err : null);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [fetchPage],
  );

  // Filters changed: start over rather than appending onto a stale list.
  useEffect(() => {
    void load(null, true);
    return () => abortRef.current?.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const loadMore = useCallback(() => {
    if (loading || !hasMore || !cursor) return;
    setLoading(true);
    void load(cursor, false);
  }, [loading, hasMore, cursor, load]);

  const reload = useCallback(() => {
    setLoading(true);
    void load(null, true);
  }, [load]);

  return { items, loading, error, hasMore, loadMore, reload };
}
