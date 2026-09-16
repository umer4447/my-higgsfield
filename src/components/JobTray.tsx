"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useStore, modelName } from "@/lib/store";
import { presetBySlug } from "@/lib/catalog";
import Frame from "./Frame";

/**
 * The tray. Jobs keep running while you browse; this is where they land.
 * Collapsed to a bar when nothing is happening, so it never sits in the way.
 */
export default function JobTray() {
  const { state, dispatch } = useStore();
  const [open, setOpen] = useState(true);
  const [tick, setTick] = useState(0);

  const active = state.jobs.filter(
    (j) => j.status === "queued" || j.status === "running",
  );
  const recent = state.jobs.slice(0, 6);

  useEffect(() => {
    if (active.length === 0) return;
    const t = setInterval(() => setTick((v) => v + 1), 220);
    return () => clearInterval(t);
  }, [active.length]);

  useEffect(() => {
    if (active.length > 0) setOpen(true);
  }, [active.length]);

  if (recent.length === 0) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-3 pb-3">
      <div className="pointer-events-auto w-full max-w-[860px] overflow-hidden rounded-[14px] border border-line bg-bg/92 shadow-[0_20px_60px_-20px_rgba(0,0,0,0.9)] backdrop-blur-xl">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-3 px-4 py-2.5 text-left"
        >
          {active.length > 0 ? (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-safelight pulse-dot" />
          ) : (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-fix" />
          )}
          <span className="label !text-[10px] !text-fg">
            {active.length > 0
              ? `${active.length} job${active.length > 1 ? "s" : ""} developing`
              : "tray"}
          </span>
          <span className="label !text-[10px]">
            {recent.reduce((n, j) => n + j.assetIds.length, 0)} frames
          </span>
          <span className="flex-1" />
          {state.jobs.some((j) => j.status === "done" || j.status === "failed") && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                dispatch({ t: "job:clear" });
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.stopPropagation();
                  dispatch({ t: "job:clear" });
                }
              }}
              className="label !text-[10px] hover:!text-fg"
            >
              clear
            </span>
          )}
          <svg
            width="12"
            height="12"
            viewBox="0 0 12 12"
            className={`ml-2 shrink-0 text-faint transition-transform ${open ? "" : "rotate-180"}`}
            aria-hidden
          >
            <path d="M2 8l4-4 4 4" stroke="currentColor" strokeWidth="1.4" fill="none" />
          </svg>
        </button>

        {open && (
          <div className="max-h-[42vh] overflow-y-auto border-t border-line-soft">
            {recent.map((job) => {
              const assets = state.assets.filter((a) => job.assetIds.includes(a.id));
              const preset = job.presetSlug ? presetBySlug(job.presetSlug) : null;
              const age = Date.now() - job.createdAt + tick * 0;
              const pct =
                job.status === "done"
                  ? 100
                  : job.status === "failed"
                    ? 100
                    : Math.min(94, 8 + (1 - Math.exp(-age / 9000)) * 92);

              return (
                <div key={job.id} className="border-b border-line-soft px-4 py-3 last:border-0">
                  <div className="flex items-start gap-3">
                    <div className="flex -space-x-2">
                      {assets.slice(0, 4).map((a) => (
                        <Link
                          key={a.id}
                          href={`/a/${a.id}`}
                          className="block h-11 w-11 shrink-0 overflow-hidden rounded-[6px] border border-line ring-1 ring-black/40"
                        >
                          <Frame asset={a} rounded="" className="!aspect-square h-full w-full" play={false} />
                        </Link>
                      ))}
                      {assets.length === 0 && (
                        <div className="h-11 w-11 rounded-[6px] border border-line bg-raised" />
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] text-fg">{job.prompt}</p>
                      <p className="label mt-1 !text-[9px] truncate">
                        {modelName(job.modelId)}
                        {preset ? ` · ${preset.name}` : ""} · {job.batch} out ·{" "}
                        {job.cost} cr
                        {job.status === "failed" ? ` · ${job.error}` : ""}
                      </p>
                      <div className="mt-2 h-[2px] w-full overflow-hidden rounded-full bg-line-soft">
                        <div
                          className="h-full rounded-full transition-[width] duration-300 ease-out"
                          style={{
                            width: `${pct}%`,
                            background:
                              job.status === "failed"
                                ? "var(--stop)"
                                : job.status === "done"
                                  ? "var(--fix)"
                                  : "var(--safelight)",
                          }}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
