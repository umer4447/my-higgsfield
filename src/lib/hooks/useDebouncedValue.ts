"use client";

import { useEffect, useState } from "react";

/**
 * 300ms is long enough to skip intra-word keystrokes and short enough to feel
 * live. Below ~200ms you are firing per keystroke with extra steps.
 *
 * The cleanup IS the debounce: each new value cancels the pending timer.
 */
export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return settled;
}
